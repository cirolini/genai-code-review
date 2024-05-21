import requests
from bs4 import BeautifulSoup

def get_scifi_movies_from_imdb():
    url = "https://www.imdb.com/search/title/?genres=sci-fi&title_type=feature&sort=moviemeter,asc"
    response = requests.get(url)
    if response.status_code != 200:
        print("Failed to retrieve page")
        return []

    soup = BeautifulSoup(response.content, 'html.parser')
    movies = []
    
    for movie_div in soup.find_all('div', class_='lister-item mode-advanced'):
        header = movie_div.find('h3', class_='lister-item-header')
        title = header.find('a').text
        year = header.find('span', class_='lister-item-year').text.strip('()')
        movies.append({'title': title, 'year': year})

    return movies

scifi_movies = get_scifi_movies_from_imdb()
for movie in scifi_movies:
    print(f"{movie['title']} ({movie['year']})")
