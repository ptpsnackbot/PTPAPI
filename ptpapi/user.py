import re

from bs4 import BeautifulSoup as bs4

import api
from session import session
from movie import Movie

class User:
    """A primitive class to represent a user"""
    def __init__(self, ID):
        # Requires an ID, as searching by name isn't exact on PTP
        self.ID = ID

    def __repr__(self):
        return "<ptpapi.User ID %s>" % self.ID

    def __str__(self):
        return "<ptpapi.User ID %s>" % self.ID

    def bookmarks(self):
        """Fetch a list of movies the user has bookmarked

        :rtype: array of Movies"""
        r = session.base_get('bookmarks.php', params={'id': self.ID})
        movies = []
        for m in api.util.snarf_cover_view_data(r.text):
            m['Torrents'] = []
            for g in m['GroupingQualities']:
                m['Torrents'].extend(g['Torrents'])
            movies.append(Movie(data=m))
        return movies

    def ratings(self):
        """Fetch a list of rated movies

        :rtype: array of tuples with a Movie and a rating out of 100"""
        soup = bs4(session.base_get('user.php', params={'id': self.ID, 'action': 'ratings'}).text)
        ratings = []
        for row in soup.find(id='ratings_table').tbody.find_all('tr'):
            movieID = re.search(r'id=(\d+)', row.find(class_='l_movie')['href']).group(1)
            print movieID
            r = row.find(id='user_rating_%s' % movieID).text.rstrip('%')
            ratings.append((movieID, r))
        return ratings

"""Define some additional methods that only apply to the logged in user."""
class CurrentUser(User):
    def inbox(self):
        soup = bs4(session.base_get('inbox.php').text)
        for row in soup.find(id="messageformtable").tbody.find_all('tr'):
            print {'Subject': row.find_all('td')[1].text.encode('UTF-8').strip(),
                   'Sender': row.find_all('td')[2].text,
                   'Date': row.find_all('td')[3].span['title'],
                   'ID': re.search(r'id=(\d+)', row.find_all('td')[1].a['href']).group(1)}

    def remove_snatched_bookmarks(self):
        session.base_post("bookmarks.php", data={'action': 'remove_snatched'})

    def remove_seen_bookmarks(self):
        session.base_post("bookmarks.php", data={'action': 'remove_seen'})

    def remove_uploaded_bookmarks(self):
        session.base_post("bookmarks.php", data={'action': 'remove_uploaded'})

    def hnr_zip(self):
        return session.base_get('snatchlist.php', params={'action':'hnrzip'})