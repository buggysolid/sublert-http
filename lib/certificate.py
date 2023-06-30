import json
import logging

import psycopg2
import requests
from requests import ReadTimeout

from lib.config import get_config


def lookup(domain, wildcard=True):
    lookup_data = _crt_sh_query_via_sql(domain)
    if lookup_data:
        return lookup_data
    lookup_data = _crt_sh_query_over_http(domain, wildcard)
    if lookup_data:
        return lookup_data


def _crt_sh_query_via_sql(domain):
    # note: globals into config.toml and print() -> logging.info()
    logger = logging.getLogger(f"sublert-http")
    logger.info('Querying crt.sh for %s via SQL.', domain)
    # connecting to crt.sh postgres database to retrieve subdomains.
    unique_domains = set()
    config = get_config()
    try:
        db_name = config.get('DB_NAME')
        db_host = config.get('DB_HOST')
        db_user = config.get('DB_USER')
        conn = psycopg2.connect("dbname={0} user={1} host={2}".format(db_name, db_user, db_host))
        conn.autocommit = True
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ci.NAME_VALUE NAME_VALUE FROM certificate_identity ci WHERE ci.NAME_TYPE = 'dNSName' AND reverse("
            "lower(ci.NAME_VALUE)) LIKE reverse(lower('%.{}'));".format(
                domain))
        for result in cursor.fetchall():
            if len(result) == 1:
                # First entry in tuple
                domain = result[0]
                unique_domains.update([domain])
    except psycopg2.DatabaseError as db_error:
        logger.error('Error interacting with database. {} {}' % db_error.pgcode, db_error.pgerror)
    except psycopg2.InterfaceError as db_interface_error:
        logger.error('Database interface error. {} {}' % db_interface_error.pgcode, db_interface_error.pgerror)

    return unique_domains


def _crt_sh_query_over_http(domain, wildcard=True):
    logger = logging.getLogger(f"sublert-http")
    logger.info('Querying crt.sh via HTTP.')
    crt_sh_url = f"https://crt.sh/?q=%.{domain}&output=json"
    subdomains = set()
    user_agent = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.14; rv:64.0) Gecko/20100101 Firefox/64.0'
    retries = 3
    timeout = 30
    backoff = 2
    success = False
    while retries != 0 and success is not True:
        try:
            req = requests.get(crt_sh_url, headers={'User-Agent': user_agent}, timeout=timeout,
                               verify=False)
            if req.status_code == 200:
                success = True
                content = req.content.decode('utf-8')
                data = json.loads(content)
                for subdomain in data:
                    subdomains.add(subdomain["name_value"].lower())
                return subdomains
        except (TimeoutError, ReadTimeout):
            success = False
            retries -= 1
            timeout *= backoff
            logger.error('Request to https://crt.sh timed out.')
