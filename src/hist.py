"""Load subwaydata.nyc days as hop tables (what actually ran)."""
import json, glob, datetime, zoneinfo
import numpy as np, pandas as pd
import config as C
TZ = zoneinfo.ZoneInfo('America/New_York')
MFLIP = {'M11', 'M12', 'M13', 'M14', 'M16', 'M18'}


def midnight(date):
    y, m, d = map(int, date.split('-'))
    return int(datetime.datetime(y, m, d, tzinfo=TZ).timestamp())


def load_day(folder, date, sidx):
    """-> DataFrame: dp, ap (platform ids), dep, arr (epoch s), nextdep (epoch s, departure from ap or NaN), trip (str), route"""
    st = pd.read_csv(f'{folder}/subwaydatanyc_{date}_stop_times.csv', dtype={'trip_uid': str, 'stop_id': str}, usecols=['trip_uid', 'stop_id', 'arrival_time', 'departure_time'])
    tr = pd.read_csv(f'{folder}/subwaydatanyc_{date}_trips.csv', dtype=str, usecols=['trip_uid', 'route_id'])
    st = st.merge(tr, on='trip_uid')
    st = st[st.route_id != 'SI']
    st['t'] = st.departure_time.fillna(st.arrival_time)
    st = st.dropna(subset=['t']).sort_values(['trip_uid', 't'], kind='stable').reset_index(drop=True)
    par = st.stop_id.str[:-1].replace(C.STATION_ALIAS)
    let = st.stop_id.str[-1]
    flip = (st.route_id == 'M') & par.isin(MFLIP)
    let = let.where(~flip, let.map({'N': 'S', 'S': 'N'}))
    s = par.map(sidx)
    st['p'] = s * 2 + (let == 'S')
    st = st[st.p.notna()].reset_index(drop=True)      # the feed also lists tunnel timing points (R60, R65, ...) that are not stations
    nx = st.shift(-1)
    ok = (st.trip_uid == nx.trip_uid) & st.p.notna() & nx.p.notna()
    h = pd.DataFrame({'dp': st.p[ok].astype(int), 'ap': nx.p[ok].astype(int),
                      'dep': st.departure_time.fillna(st.arrival_time)[ok], 'arr': nx.arrival_time.fillna(nx.departure_time)[ok],
                      'nextdep': nx.departure_time[ok], 'trip': st.trip_uid[ok], 'route': st.route_id[ok]})
    return h[h.arr > h.dep].reset_index(drop=True)


def stations(data):
    net = json.load(open(data + '/net.json'))
    return net, {s['id']: i for i, s in enumerate(net['stations'])}
