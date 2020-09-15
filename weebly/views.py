import hashlib
import hmac
import json
import logging
import jwt
import requests

from datetime import datetime
from urllib.parse import urlencode

from django.urls import reverse
from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect, HttpResponseBadRequest
from django.utils.timezone import make_aware
from django.views.defaults import bad_request
from django.views.decorators.csrf import csrf_exempt
from django.utils.deprecation import MiddlewareMixin
from django.utils.version import get_version_tuple

from marto_python.url import get_server_url
from .models import WeeblyAuth
from .signals import webhooks_signal, app_installed_signal

logger = logging.getLogger(__name__)

SESSION_APP_INSTALLED_FLAG = 'app_installed'


class RequiresWeeblyAuth:
    """
    Decorator to be used with WeeblyAuthMiddleware.
    Says that the view is for authenticated users only.
    """
    def __init__(self, f):
        self.requires_weebly_auth = True
        self.f = f

    def __call__(self, *args, **kwargs):
        return self.f(*args, **kwargs)

    @staticmethod
    def view_requires(view_func):
        """
        takes a view and says if the view requires a weebly authenticated user
        """
        try:
            return view_func.requires_weebly_auth
        except AttributeError:
            return False


class WeeblyAuthMiddleware(MiddlewareMixin):
    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def process_view(self, request, view_func, view_args, view_kwargs):
        """
        Checks if weebly authentication is needed and
        if so, allows the view only when there is an authenticated user
        """
        request.weebly_auth = None
        if not RequiresWeeblyAuth.view_requires(view_func): return None
        request.weebly_auth = WeeblyAuthMiddleware.get_weebly_auth(request)
        if request.weebly_auth and request.weebly_auth.auth_token:
            return None
        return bad_request(request, None, template_name='missing_weebly_auth.html')

    @staticmethod
    def get_weebly_auth(request):
        """
        Returns the weebly_auth from different sources or None if can't find one.
        Stores the found weebly_auth in the session for further use.
        Looks for it in:
            -jwt parameter in the URL
            -the session
            -or the first weebly_auth if not PRODUCTION (for testing purposes)
        """
        if 'jwt' in request.GET:
            # in case of auth authentication, jwt is there but no weebly_auth in the DB
            jwt_key = request.GET['jwt']
            try:
                decoded = jwt.decode(jwt_key,
                                     settings.WEEBLY_SECRET,
                                     algorithms=['HS256'],
                                     options={'verify_iat': False})
            except jwt.DecodeError as e:
                logger.error(f'Error decoding jwt - {e}', exc_info=True)
                return None
            user_id = decoded['user_id']
            site_id = decoded['site_id']
            weebly_auth = WeeblyAuth.objects.filter(user__user_id=user_id, site__site_id=site_id).first()
        elif request.user.is_superuser and 'weebly_auth' in request.GET:
            weebly_auth_id = int(request.GET['weebly_auth'])
            weebly_auth = WeeblyAuth.objects.filter(pk=weebly_auth_id).first()
        elif 'weebly_auth' in request.session:
            weebly_auth = WeeblyAuthMiddleware.get_session_auth_info(request)
        else:
            weebly_auth = None
        if weebly_auth:
            WeeblyAuthMiddleware.set_session_auth_info(request, weebly_auth)
        elif 'weebly_auth' in request.session:
            del request.session['weebly_auth']
        return weebly_auth

    @staticmethod
    def set_session_auth_info(request, weebly_auth):
        auth_info = {
            'user_id': weebly_auth.user.user_id,
            'site_id': weebly_auth.site.site_id
        }
        session_auth_info = request.session.get('weebly_auth', None)
        if auth_info != session_auth_info:
            request.session.clear()
            request.session['weebly_auth'] = auth_info

    @staticmethod
    def get_session_auth_info(request):
        auth_info = request.session.get('weebly_auth', None)
        if not auth_info:
            return None
        user_id = auth_info['user_id']
        site_id = auth_info['site_id']
        return WeeblyAuth.objects.filter(user__user_id=user_id, site__site_id=site_id).first()


def weebly_oauth(request):
    """
    This method has the whole OAUTH authorization flow
    """
    params = request.GET
    if 'user_id' not in params or 'site_id' not in params:
        return HttpResponseBadRequest('Missing user site info')
    user_id = params['user_id']
    site_id = params['site_id']
    timestamp = int(params['timestamp'])
    version = params.get('version', None)
    weebly_auth = WeeblyAuth.get_or_create(user_id, site_id, version)
    weebly_auth.timestamp = make_aware(datetime.fromtimestamp(timestamp))
    weebly_auth.save()

    callback_url = params['callback_url']
    if 'hmac' in params:
        logger.info(f'{weebly_auth} - first oauth call')
        hmac_code = params['hmac']
        hash_string = f"user_id={user_id}&timestamp={timestamp}&site_id={site_id}"
        if not validate_hmac(hmac_code, hash_string):
            logger.warning(f'{weebly_auth} - The hmac signature did not validate')
            return HttpResponseBadRequest('<h1>The hmac signature did not validate</h1>')
        response_params = {
            'client_id': settings.WEEBLY_CLIENT_ID,
            'user_id': params['user_id'],
            'site_id': params['site_id'],
            'version': params['version'],
            'redirect_uri': get_server_url() + reverse(weebly_oauth)
        }
    elif 'authorization_code' in params:
        token_msg = 'already have token' if weebly_auth.auth_token else 'requesting auth token...'
        logger.info( f'{weebly_auth} - second oauth call - {token_msg}')

        response = requests.post(params['callback_url'], {
            'client_id': settings.WEEBLY_CLIENT_ID,
            'client_secret': settings.WEEBLY_SECRET,
            'authorization_code': params['authorization_code'],
        })
        response_json = response.json()
        if 'error' in response_json:
            error_msg = f'{weebly_auth} - access_token missing in weebly response - error: {response_json["error"]}'
            logger.error(error_msg)
            return HttpResponseBadRequest(response.content)
        if 'access_token' in response_json:
            weebly_auth.auth_token = response_json['access_token']
            weebly_auth.save()
            logger.info(f'{weebly_auth} - auth token received {weebly_auth.auth_token}')

        refresh_user_site_from_weebly(weebly_auth)
        app_installed_signal.send(sender=weebly_auth)
        set_app_installed(request)

        callback_url = response_json['callback_url']
        response_params = {'client_id': settings.WEEBLY_CLIENT_ID}
    else:
        return HttpResponseBadRequest('Did not expect this!')

    redirect_url = f'{callback_url}?{urlencode(response_params)}'
    logger.info(f'{weebly_auth} - redirecting to {redirect_url}')
    return HttpResponseRedirect(redirect_url)


def set_app_installed(request):
    request.session[SESSION_APP_INSTALLED_FLAG] = True


def pop_app_installed(request):
    return request.session.pop(SESSION_APP_INSTALLED_FLAG, default=False)


def refresh_user_site_from_weebly(weebly_auth):
    """
    updates user and site info from weebly
    """
    weebly_auth.user.refresh_from_weebly(weebly_auth)
    weebly_auth.site.refresh_from_weebly(weebly_auth)


def validate_hmac(hmac_code, hash_string):
    """
    checks if the provided hmac code matches the hmac code generated from the hash string
    """
    return hmac_code == get_hmac_code(settings.WEEBLY_SECRET, hash_string)


def get_hmac_code(secret_string, hash_string, digest_mode=hashlib.sha256):
    return hmac.new(secret_string.encode('utf-8'), hash_string.encode('utf-8'), digest_mode).hexdigest()


@csrf_exempt
def weebly_webhooks(request):
    """
    process webhooks from weebly and send a webhooks signal
    """
    if request.method == 'HEAD': return HttpResponse()

    data = json.loads(request.body)
    hash_string = request.body.decode()
    hash_parts = hash_string.split(',"hmac":"')
    hash_parts[1] = hash_parts[1].split('"', 2)[1]
    hash_string = hash_parts[0] + hash_parts[1]
    if not validate_hmac(data['hmac'], hash_string):
        logger.error('The hmac signature did not validate %s' % request.body)
        return HttpResponseBadRequest()
    else:
        event = data['event']
        client_id = data['client_id']
        client_version = data['client_version']
        logger.info(f'webhook event {event} for client {client_id} - version {client_version}')
        signal_data = {'request': request}
        signal_data.update(data)
        ts = make_aware(datetime.fromtimestamp(data['timestamp']))
        data = data['data']
        user_id = data['user_id']
        site_id = data['site_id']
        weebly_auth = WeeblyAuth.objects.get(user__user_id=user_id, site__site_id=site_id)
        site = weebly_auth.site
        client_version_tuple = get_version_tuple(client_version)
        weebly_auth_version_tuple = get_version_tuple(weebly_auth.version)
        if client_version_tuple < weebly_auth_version_tuple:
            logger.warning(f'{site} - ignoring webhooks with lower version {client_version}')
        else:
            # using > instead of != because the weebly bug that can sends many webhooks calls for the same event
            if client_version_tuple > weebly_auth_version_tuple:
                logger.info(f'{site} - upgraded from version {weebly_auth.version} to {client_version}')
                weebly_auth.version = client_version
                weebly_auth.save()

            webhooks_signal.send(sender=None,
                                 event=event,
                                 weebly_auth=weebly_auth,
                                 client_id=client_id,
                                 client_version=client_version,
                                 timestamp=ts,
                                 data=data)
    return HttpResponse()
