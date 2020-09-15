import logging
import html
import json
from django.db import IntegrityError
from marto_python.email.email import send_email_to_admins
from marto_python.util import is_valid_email
from marto_python.collections import map_dict


logger = logging.getLogger(__name__)


def update_list_of(site,
                   json_data,
                   object_name,
                   id_property_elem,
                   id_property_data,
                   new_elem_func,
                   related_manager,
                   properties_mapping):
    """
    updates the list of things in the database according to a response from weebly api

    params:

    site:               the weebly site object
    json_data:          the json data from the weebly api response
    object_name:        the name of the object, for logging
    id_property_elem:   the name of the id property in the model
    id_property_data:   the name of the id property in the json data
    new_elem_func:      function that creates a new object
    related_manager:    the related manager for the list of objects to be updated
    properties_mapping:
        a list of 3-uples for mapping properties in the response to the model
        (response property name, model property name, function that translates from response to model value)
    """

    log_strs = []

    def log(log_msg, log=False):
        if log: logger.info(f'{site} - {log_msg}')
        log_strs.append(log_msg)

    changes = False
    for original_elem in related_manager.all():
        elem_id = getattr(original_elem, id_property_elem)
        if not find_in_map_list(json_data, id_property_data, elem_id):
            changes = True
            log(f'deleting - {object_name} {original_elem.pk}', log=True)
            original_elem.delete()
    related_manager.update()
    for data_elem in json_data:
        data_id = int(data_elem[id_property_data])
        related_manager.update()
        elem_qs = related_manager.filter(**{id_property_elem: data_id})
        is_new = not elem_qs.exists()
        try:
            if is_new:
                log(f'creating - {object_name} {data_id}', log=True)
                elem = new_elem_func()
                setattr(elem, id_property_elem, data_id)
                update_object_from_data(elem, properties_mapping, data_elem)
                elem.save()
                related_manager.add(elem)
                changes = True
            else:
                log(f'already exists - {object_name} {data_id}')
                elem = elem_qs.first()
                save = update_object_from_data(elem, properties_mapping, data_elem)
                if save:
                    log('saving - %s %s' % (object_name, data_id), log=True)
                    changes = True
                    elem.save()
        except IntegrityError:
            new_or_old = 'new' if is_new else 'old' # FIXME: remove all this for django-weebly
            logger_msg = f'{site} - integrity error {object_name} {data_id} {new_or_old}'
            logger.error(logger_msg, exc_info=True)
            log('')
            log('Data:')
            log('')
            log(json.dumps(json_data, indent=4))
            send_email_to_admins(logger_msg, '<br/>'.join(log_strs))
            log_strs = []
    return {'changes': changes}


def update_object_from_data(obj, properties_mapping, data):
    """
    updates the object and returns true if the object must be saved
    Does NOT save
    """
    save = False
    for data_property, obj_property, transform_func in properties_mapping:
        obj_val = getattr(obj, obj_property)
        data_val = data[data_property]
        if transform_func:
            data_val = transform_func(data_val)
        if obj_val != data_val:
            setattr(obj, obj_property, data_val)
            save = True
    return save


def compose(f, g):
    return lambda x: f(g(x))


def none_to_empty(val):
    return val if val else ''


def unescape_func_not_null(val):
    val = none_to_empty(val)
    return unescape_func(val)


def unescape_func(val):
    """
    helper for update funcs
    """
    if not val: return val
    val = val.replace('&amp;amp;', '&')  # Fixing strange weebly double HTML encoding
    return html.unescape(val) if val is not None else None


def unescape_dict_val_func(val):
    if not val: return val
    return map_dict(val, lambda tag, name: html.unescape(name))


def valid_email_func(val):
    return val if is_valid_email(val) else None


def find_in_map_list(l, property_name, id_value):
    for elem in l:
        elem_id = int(elem[property_name])
        if elem_id == id_value:
            return elem
    return None
