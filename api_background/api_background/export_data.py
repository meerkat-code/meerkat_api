"""

Functions to export data



"""
from sqlalchemy import text, or_
from sqlalchemy.orm import aliased
import io
import csv
import json
from dateutil.parser import parse
from datetime import datetime
from celery import task

from meerkat_abacus.util import epi_week, get_locations, all_location_data, get_db_engine, get_links
from meerkat_abacus.model import form_tables, Data, DownloadDataFiles, AggregationVariables
from meerkat_abacus.config import country_config, config_directory


@task

def export_data(uuid, use_loc_ids=False):
    db, session = get_db_engine()
    results = session.query(Data)
    variables = set()
    locs = get_locations(session)
    for row in results:
        variables = variables.union(set(row.variables.keys()))
    fieldnames = ["id", "country", "region", "district", "clinic",
                      "clinic_type", "geolocation", "date", "uuid"
                  ] + list(variables)
    dict_rows = []
    for row in results:
        dict_row = dict((col, getattr(row, col))
                    for col in row.__table__.columns.keys())
        if not use_loc_ids:
            for l in ["country", "region", "district", "clinic"]:
                if dict_row[l]:
                    dict_row[l] = locs[dict_row[l]].name
        dict_row.update(dict_row.pop("variables"))
        dict_rows.append(dict_row)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(dict_rows)
    session.add(
            DownloadDataFiles(
                uuid=uuid,
                content=output.getvalue(),
                generation_time=datetime.now(),
                type="data",
                success=1,
                status=1
                )
            )
    session.commit()
    return True


@task
def export_category(uuid, form_name, category, download_name, variables):
    db, session = get_db_engine()
    res = session.query(AggregationVariables).filter(
        AggregationVariables.category.has_key(category)
        )
    
    data_keys = []
    cat_variables = {}
    for r in res:
        data_keys.append(r.id)
        cat_variables[r.id] = r
    if len(data_keys) == 0:
        session.add(
            DownloadDataFiles(
                uuid=uuid,
                content="",
                generation_time=datetime.now(),
                type=download_name,
                success=0,
                status=1
                )
            )
        session.commit()
    return_keys = []
    translation_dict = {}
    icd_code_to_name = {}
    link_ids = []
    min_translation = {}

    # Set up icd_code_to_name if needed and determine if
    # alert_links are included
    for v in variables:
        return_keys.append(v[1])
        if "icd_name$" in v[0]:
            category = v[0].split("$")[1]
            icd_code_to_name[v[0]] = {}
            for i in cat_variables.keys():
                condition = cat_variables[i].condition
                if "," in condition:
                    # If a variable have many icd codes
                    # we take all of them into account
                    codes = condition.split(",")
                else:
                    codes = [condition]
                for c in codes:
                    icd_code_to_name[v[0]][c.strip()] = cat_variables[i].name
        if "$translate" in v[0]:
            split = v[0].split("$")
            field = "$".join(split[:-1])
            trans = split[-1]
            tr_dict = json.loads(trans.split(";")[1].replace("'", '"'))
            min_translation[v[1]] = tr_dict
            v[0] = field
            print(min_translation)
        if "gen_link$" in v[0]:
            link_ids.append(v[0].split("$")[1])
        translation_dict[v[1]] = v[0]

    link_ids = set(link_ids)
    links_by_type, links_by_name = get_links(config_directory +
                                             country_config["links_file"])
    # DB query, with yield_per(200) for memory reasons

    columns = [Data, form_tables[form_name]]

    link_id_index = {}
    joins = []
    for i, l in enumerate(link_ids):
        form = aliased(form_tables[links_by_name[l]["to_form"]])
        joins.append((form, Data.links[(l, -1)].astext == form.uuid))
        link_id_index[l] = i + 2
        columns.append(form.data)

    results = session.query(*columns).join(
        form_tables[form_name], Data.uuid == form_tables[form_name].uuid)
    for join in joins:
        results = results.outerjoin(join[0], join[1])
    results = results.filter(
        or_(Data.variables.has_key(key)
            for key in data_keys)).yield_per(200)
    locs = get_locations(session)
    dict_rows = []

    # Prepare each row
    for r in results:
        dict_row = {}
        for k in return_keys:
            form_var = translation_dict[k]
            if "icd_name$" in form_var:
                if r[1].data["icd_code"] in icd_code_to_name[form_var]:
                    dict_row[k] = icd_code_to_name[form_var][r[1].data[
                        "icd_code"]]
                else:
                    dict_row[k] = None
            elif form_var == "clinic":
                dict_row[k] = locs[r[0].clinic].name
            elif form_var == "region":
                dict_row[k] = locs[r[0].region].name
            elif form_var == "district":
                if r[0].district:
                    dict_row[k] = locs[r[0].district].name
                else:
                    dict_row[k] = None
            elif "$year" in form_var:
                field = form_var.split("$")[0]
                if field in r[1].data and r[1].data[field]:
                    dict_row[k] = parse(r[1].data[field]).year
                else:
                    dict_row[k] = None
            elif "$month" in form_var:
                field = form_var.split("$")[0]
                if field in r[1].data and r[1].data[field]:
                    dict_row[k] = parse(r[1].data[field]).month
                else:
                    dict_row[k] = None
            elif "$epi_week" in form_var:
                field = form_var.split("$")[0]
                if field in r[1].data and r[1].data[field]:
                    dict_row[k] = epi_week(parse(r[1].data[field]))[0]
                else:
                    dict_row[k] = None

            # A general framework for referencing links in the
            # download data.
            # link$<link id>$<linked form field>
            elif "gen_link$" in form_var:
                link = form_var.split("$")[1]
                link_index = link_id_index[link]
                if r[link_index]:
                    dict_row[k] = r[link_index][form_var.split("$")[-1]]
                else:
                    dict_row[k] = None

            elif "code" == form_var.split("$")[0]:
                # code$cod_1,cod_2,Text_1,Text_2$default_value
                split = form_var.split("$")
                codes = split[1].split(",")
                text = split[2].split(",")
                if len(split) > 3:
                    default_value = split[3]
                else:
                    default_value = None
                final_text = []
                for i in range(len(codes)):
                    if codes[i] in r[0].variables:
                        final_text.append(text[i])
                if len(final_text) > 0:
                    dict_row[k] = " ".join(final_text)
                else:
                    dict_row[k] = default_value

            elif "code_value" == form_var.split("$")[0]:
                code = form_var.split("$")[1]
                if code in r[0].variables:
                    dict_row[k] = r[0].variables[code]
                else:
                    dict_row[k] = None
            elif "value" == form_var.split(":")[0]:
                dict_row[k] = form_var.split(":")[1]
            else:
                if form_var in r[1].data:
                    dict_row[k] = r[1].data[form_var]
                else:
                    dict_row[k] = None

            if min_translation and k in min_translation:
                tr_dict = min_translation[k]
                if dict_row[k] in tr_dict.keys():
                    dict_row[k] = tr_dict[dict_row[k]]

        dict_rows.append(dict_row)
    output = io.StringIO()
    writer = csv.DictWriter(output, return_keys, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(dict_rows)
    session.add(
            DownloadDataFiles(
                uuid=uuid,
                content=output.getvalue(),
                generation_time=datetime.now(),
                type=download_name,
                success=1,
                status=1
                )
            )
    session.commit()
    return True



@task
def export_form(uuid, form, fields=None):
    db, session = get_db_engine()
    (locations, locs_by_deviceid, regions,
     districts, devices) = all_location_data(session)
    if fields:
        keys = fields
    else:
        keys = ["clinic", "region", "district"]
        if form not in form_tables:
            return {"filename": form, "file": io.StringIO()}
        sql = text("SELECT DISTINCT(jsonb_object_keys(data)) from {}".
                   format(form_tables[form].__tablename__))
        result = db.execute(sql)
        for r in result:
            keys.append(r[0])
            
    f = io.StringIO()
    csv_writer = csv.DictWriter(f, keys, extrasaction='ignore')
    csv_writer.writeheader()
    i = 0
    if locs_by_deviceid is None:
        session.add(
            DownloadDataFiles(
                uuid=uuid,
                content="",
                generation_time=datetime.now(),
                type=form,
                success=0,
                status=1
                )
            )
        session.commit()
        return False
        
    if form in form_tables.keys():
        results = session.query(form_tables[form].data).yield_per(1000)
        dict_rows = []
        for row in results:
            dict_row = row.data
            if not dict_row:
                continue
            clinic_id = locs_by_deviceid.get(dict_row["deviceid"], None)
            if clinic_id:
                dict_row["clinic"] = locations[clinic_id].name
                # Sort out district and region
                if locations[clinic_id].parent_location in districts:
                    dict_row["district"] = locations[locations[clinic_id]
                                                     .parent_location].name
                    dict_row["region"] = locations[locations[locations[
                        clinic_id].parent_location].parent_location].name
                elif locations[clinic_id].parent_location in regions:
                    dict_row["district"] = ""
                    dict_row["region"] = locations[locations[clinic_id]
                                                   .parent_location].name
            else:
                dict_row["clinic"] = ""
                dict_row["district"] = ""
                dict_row["region"] = ""
            for key in list(row.data.keys()):
                if key in keys and key not in dict_row:
                    dict_row[key] = row.data[key]
            dict_rows.append(dict_row)
            if i % 1000 == 0:
                csv_writer.writerows(dict_rows)
                dict_rows = []
            i += 1
        csv_writer.writerows(dict_rows)
        session.add(
            DownloadDataFiles(
                uuid=uuid,
                content=f.getvalue(),
                generation_time=datetime.now(),
                type=form,
                success=1,
                status=1
                )
            )
        session.commit()
        
        return True

    
