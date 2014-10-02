#!/bin/env python
import ConfigParser
import re
import os
import pickle
from datetime import datetime

from bs4 import BeautifulSoup as bs4
import requests

import util

session = requests.Session()
def print_callback(r, *args, **kwargs):
    print(r.url)
session.hooks.update({'response': print_callback})
session.headers.update({"User-Agent": "Wget/1.13.4"})

baseURL = 'https://tls.passthepopcorn.me/'
cookiesFile = 'cookies.txt'

def login(**kwargs):
    return API(**kwargs)

class PTPAPIException(Exception):
    pass

class TokenBucket(object):
    def __init__(self, tokens, fill_rate):
        """tokens is the total tokens in the bucket. fill_rate is the
        rate in tokens/second that the bucket will be refilled."""
        self.capacity = float(tokens)
        self._tokens = float(tokens)
        self.fill_rate = float(fill_rate)
        self.timestamp = time()
        
    def consume(self, tokens):
        """Consume tokens from the bucket. Returns True if there were
        sufficient tokens otherwise False."""
        self.get_tokens()
        if tokens <= self.tokens:
            self._tokens -= tokens
        else:
            return False
        return True

    def get_tokens(self):
        if self._tokens < self.capacity:
            now = time()
            delta = self.fill_rate * (now - self.timestamp)
            self._tokens = min(self.capacity, self._tokens + delta)
            self.timestamp = now
        return self._tokens
        
    tokens = property(get_tokens)
    
class Movie:
    def __init__(self, ID=None, data=None):
        # Expects either a groupd ID to load data from, or for the data to already be present
        self.torrents = []
        if data:
            self.data = data
            self.ID = data['GroupId']
        elif ID:
            self.ID = ID
            self.data = {}
            self.load_data()
        else:
            raise PTPAPIException("Could not load necessary data for Movie class")
        if self.data['Torrents']:
            for t in self.data['Torrents']:
                self.torrents.append(Torrent(data=t))

    def load_data(self, basic=True, overwrite=False):
        # Check to see if data has already been set
        if not 'GroupId' in self.data or overwrite:
            self.data = session.get(baseURL + "torrents.php",
                                    params={'id': self.ID,
                                            'json': '1'}).json()
            if self.data['Torrents']:
                self.torrents = []
                for t in self.data['Torrents']:
                    self.torrents.append(Torrent(data=t))
        # Don't make two http calls unless told to
        if not basic and not overwrite:
            soup = bs4(session.get(baseURL + "torrents.php", params={'id':self.ID}).text)
            for t in self.torrents:
                # Get file list
                filediv = soup.find("div", id="files_%s" % t.ID)
                t.data['Filelist'] = {}
                for e in filediv.find("tbody").find_all("tr"):
                    bytesize = e("td")[1]("span")[0]['title'].replace(",","").replace(' bytes', '')
                    t.data['Filelist'][e("td")[0].string] = bytesize

class Torrent:
    def __init__(self, ID=None, data=None, load=True):
        if data:
            self.data = data
            if 'Id' in data:
                self.ID = data['Id']
            elif 'TorrentId' in data:
                self.ID = data['TorrentId']
            else:
                raise PTPAPIException("Could not find torrent ID in data")
        elif ID:
            self.ID = ID
            if load:
                self.load_data()
        else:
            raise PTPAPIException("Not enough information to intialize torrent")

    def load_data(self):
        # This has no 'basic' parameter, because it takes two calls to get the basic info anyway
        movieID = re.search(r'\?id=(\d+)', session.get(baseURL + 'torrents.php', params={'torrentid': self.ID}).url).group(1)
        self.data = session.get(baseURL + 'torrents.php',
                                params={'torrentid': self.ID,
                                        'id': movieID,
                                        'json':'1'})

    def download(self):
        r = session.get(baseURL + "torrents.php",
                        params={'action': 'download',
                                'id': self.ID})
        self.downloadName = re.search(r'filename="(.*)"', r.headers['Content-Disposition']).group(1)
        return r.content

    def download_to_file(self, dest=None, name=None):
        r = session.get(baseURL + "torrents.php",
                        params={'action': 'download',
                                'id': self.ID})
        if not dest:
            dest = os.getcwd()
        if not name:
            name = re.search(r'filename="(.*)"', r.headers['Content-Disposition']).group(1)
        with open(os.path.join(dest, name), 'wb') as fh:
            fh.write(r.content)
        return os.path.join(dest, name)

class User:
    def __init__(self, ID):
        # Requires an ID, as searching by name isn't exact on PTP
        self.ID = ID

    def load_data(self):
        pass

    def bookmarks(self, filters=None):
        r = session.get(baseURL + 'bookmarks.php', params={'id': self.ID})
        movies = []
        for m in util.snarf_cover_view_data(r.text):
            m['Torrents'] = []
            for g in m['GroupingQualities']:
                m['Torrents'].extend(g['Torrents'])
            movies.append(Movie(data=m))
        return movies

class API:
    def __init__(self, conf=None, username=None, password=None, passkey=None):
        global session
        j = None
        if os.path.isfile(cookiesFile):
            self.load_cookies()
            session.max_redirects = 1
            try:
                r = session.get(baseURL + 'torrents.php')
            except requests.exceptions.TooManyRedirects:
                os.remove(cookiesFile)
                session.cookies = requests.cookies.RequestsCookieJar()
            session.max_redirects = 3
        if not os.path.isfile(cookiesFile):
            if conf:
                config = ConfigParser.ConfigParser()
                config.read(conf)
                username = config.get('PTP', 'username')
                password = config.get('PTP', 'password')
                passkey = config.get('PTP', 'passkey')
            if not password or not passkey or not username:
                raise PTPAPIException("Not enough info provided to log in.")
            try:
                j = session.post(baseURL + 'ajax.php?action=login',
                                 data={"username": username,
                                       "password": password,
                                       "passkey": passkey }).json()
            except ValueError as e:
                raise PTPAPIException("Could not parse returned json data.")
            if j["Result"] != "Ok":
                raise PTPAPIException("Failed to log in. Please check the username, password and passkey. Response: %s" % j)
            self.save_cookie()
            # Get some information that will be useful for later
            r = session.get(baseURL + 'index.php')
        self.current_user_id = re.search(r'user.php\?id=(\d+)', r.text).group(1)
        self.auth_key = re.search(r'auth=([0-9a-f]{32})', r.text).group(1)

    def logout(self):
        os.remove(cookiesFile)
        return session.get(baseURL + 'logout.php', params={'auth': self.auth_key})

    def save_cookie(self):
        with open(cookiesFile, 'w') as fh:
                pickle.dump(requests.utils.dict_from_cookiejar(session.cookies), fh)

    def load_cookies(self):
        global session
        with open(cookiesFile) as fh:
            session.cookies = requests.utils.cookiejar_from_dict(pickle.load(fh))

    def current_user(self):
        return User(self.current_user_id)
        
    def search(self, filters):
        if 'name' in filters:
            filters.update({'searchstr': filters['name']})
        filters.update({'json': 'noredirect'})
        return [Movie(data=m) for m in session.get(baseURL + 'torrents.php', params=filters).json()['Movies']]

    def remove_snatched_bookmarks(self):
        session.post(baseURL + "bookmarks.php", data={'action': 'remove_snatched'})

    def remove_seen_bookmarks(self):
        session.post(baseURL + "bookmarks.php", data={'action': 'remove_seen'})

    def remove_uploaded_bookmarks(self):
        session.post(baseURL + "bookmarks.php", data={'action': 'remove_uploaded'})

    def need_for_seed(self):
        data = util.snarf_cover_view_data(session.get(baseURL + "needforseed.php").content)
        return [t['GroupingQualities'][0]['Torrents'][0] for t in data]

def best_match(movie, profile, allow_dead=False):
    # We're going to emulate what.cd's collector option
    profiles = profile.lower().split(',')
    current_sort = None
    for p in profiles:
        matches = movie.torrents
        filter_dict = {
            'gp': (lambda t: t.data['GoldenPopcorn']),
            'scene': (lambda t: t.data['Scene']),
            '576p': (lambda t: t.data['Resolution'] == '576p'),
            '480p': (lambda t: t.data['Resolution'] == '480p'),
            '720p': (lambda t: t.data['Resolution'] == '720p'),
            '1080p': (lambda t: t.data['Resolution'] == '1080p'),
            'HD': (lambda t: t.data['Quality'] == 'High Definition'),
            'SD': (lambda t: t.data['Quality'] == 'Standard Definition'),
            'Remux': (lambda t: 'remux' in t.data['RemasterTitle'].lower()),
            'x264': (lambda t: t.data['Codec'] == 'x264')
        }
        for (name, func) in filter_dict.items():
            if name.lower() in p:
                matches = [t for t in matches if func(t)]
        sort_dict = {
            'most recent': (True, (lambda t: datetime.strptime(t.data['UploadTime'], "%Y-%m-%d %H:%M:%S"))),
            'smallest': (False, (lambda t: t.data['Size'])),
            'seeded': (True, (lambda t: t.data['Seeders'])),
            'largest': (True, (lambda t: t.data['Size'])),
        }
        for name, (rev, sort) in sort_dict.items():
            if name in p:
                current_sort = name
        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1 and current_sort:
            (rev, sort) = sort_dict[current_sort]
            return sorted(matches, key=sort, reverse=rev)[0]
    return None
