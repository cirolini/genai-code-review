import requests

def get_imdb_movies(page_number):
    url = "https://api.themoviedb.org/3/discover/movie?api_key=YOUR_API_KEY&language=pt-BR&sort_by=popularity.desc&page={}".format(page_number)
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data["results"]
    else:
        return None


def main():
    # Obtém a lista de filmes da página 1
    movies = get_imdb_movies(1)

    # Imprime os títulos dos filmes
    for movie in movies:
        print(movie["title"])


if __name__ == "__main__":
    main()
