"""
meerkat_api util functions

"""
from datetime import datetime
from flask import jsonify


def row_to_dict(row):
    """
    Translate sql alchemy row to dict

    Args:
    row: SQL alchemy class

    Returns:
      data_dict(dict): data as dictionary
    """
    if hasattr(row, "__table__"):
        return dict((col, getattr(row, col))
                    for col in row.__table__.columns.keys())
    else:
        ret = {}
        for table in row:
            if table:
                ret[table.__tablename__] = dict(
                    (col, getattr(table, col)) for col
                    in table.__table__.columns.keys())
        return ret


def rows_to_dicts(rows, dict_id=None):
    """
    Translate sql alchemy rows to dicts

    Args:
       rows: List of SQL alchemy rows
       dict_id: If True we return a dict with the dict_id column as index
    Returns:
       data_dicts(dict): data as dictionary
    """
    if dict_id:
        if len(rows) >0 and isinstance(rows[0], tuple):
            raise TypeError("Can not use dict_id=True with tuple rows")
        data_dicts = {}
        for row in rows:
            data_dicts[getattr(row, dict_id)] = row_to_dict(row)
    else:
        data_dicts = []
        for row in rows:
            data_dicts.append(row_to_dict(row))
    return data_dicts


def is_child(parent, child, locations):
    """
    Determines if child is child of parent

    Args:
        parent: parent_id
        child: child_id
        locations: all locations in dict

    Returns:
       is_child(Boolean): True if child is child of parent
    """
    parent = int(parent)
    child = int(child)
    if child == parent or parent == 1:
        return True
    loc_id = child
    while loc_id != 1:
        loc_id = locations[loc_id].parent_location
        if loc_id == parent:
            return True
    return False


def get_children(parent, locations, clinic_type=None):
    """
    Return all clinics that are children of parent

    Args:
        parent: parent_id
        locations: all locations in dict

    Returns:
       list of location ids
    """
    ret = []
    for location_id in locations.keys():
        if (locations[location_id].case_report and
            (not clinic_type or locations[location_id].clinic_type == clinic_type)):
            if is_child(parent, location_id, locations):
                ret.append(location_id)
    return ret
