import pandas as pd
import streamlit as st
import pickle

movies_dict = pickle.load(open('movies_dict.pkl', 'rb'))
movies = pd.DataFrame(movies_dict)
similarity = pickle.load(open('similarity.pkl', 'rb'))

def recommend(movie):
    movie_index = movies[movies['title'] == movie].index[0]
    distance = similarity[movie_index]
    movies_list = sorted(list(enumerate(distance)), reverse=True, key=lambda x: x[1])[1:6]

    recommended_movies = []
    for i in movies_list:
        recommended_movies.append(movies.iloc[i[0]].title)

    return recommended_movies


st.title('Movie Recommender')

selected_movie_name = st.selectbox(
    'Which movie do you want recommendations for?',
    movies['title'].values
)

if st.button('Recommend'):
    names = recommend(selected_movie_name)
    for name in names:
        st.text(name)
