import pandas as pd

# Ler arquivo CSV
data = pd.read_csv('dados.csv')

# Imprimir as primeiras 5 linhas dos dados
print(data.head())

# Imprimir o número de linhas e colunas dos dados
print('Número de linhas: ', data.shape[0])
print('Número de colunas: ', data.shape[1])

# Imprimir informações estatísticas básicas dos dados
print(data.describe())
