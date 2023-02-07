import pandas as pd

# Lê o arquivo CSV
df = pd.read_csv("nome_do_arquivo.csv")

# Exibe as primeiras linhas do DataFrame
print(df.head())

# Modifica o nome da coluna "Coluna Antiga" para "Nova Coluna"
df.rename(columns={"Coluna Antiga": "Nova Coluna"}, inplace=True)

# Adiciona uma nova coluna "Coluna Adicionada" com o valor 0 em todas as linhas
df["Coluna Adicionada"] = 0

# Exibe as primeiras linhas do DataFrame após as modificações
print(df.head())
