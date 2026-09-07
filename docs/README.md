# Documentation — Veille des fermetures d'agences bancaires

Cette documentation s'adresse à quelqu'un qui reprend le projet sans le
connaître. Les fichiers sont numérotés dans leur ordre de lecture conseillé :
les trois premiers suffisent pour comprendre ce que fait l'application et la
faire tourner.

## Parcours de lecture

| # | Document | À lire si… |
|---|---|---|
| 01 | [Démarrage](01-demarrage.md) | vous voulez lancer le projet en local |
| 02 | [Architecture](02-architecture.md) | vous voulez la vue d'ensemble en 5 minutes |
| 03 | [Pipeline](03-pipeline.md) | vous devez modifier le traitement des articles |
| 04 | [Sources](04-sources.md) | vous ajoutez ou déboguez un collecteur |
| 05 | [Modèle de données](05-modele-de-donnees.md) | vous touchez au stockage ou à l'export |
| 06 | [Frontend](06-frontend.md) | vous travaillez sur la carte ou les vues |
| 07 | [Exploitation](07-exploitation.md) | un run automatique a échoué |
| 08 | [Configuration](08-configuration.md) | vous cherchez à quoi sert une variable |
| 09 | [Feuille de route](09-feuille-de-route.md) | **avant d'entreprendre quoi que ce soit de structurant** |
| 10 | [Glossaire](10-glossaire.md) | un terme du code vous échappe |

## Historique de conception

[`superpowers/`](superpowers/README.md) conserve les specs et plans de
conception rédigés cycle par cycle. Ce sont des documents **datés et
historiques** : ils expliquent pourquoi les choses sont comme elles sont, mais
la source de vérité sur l'état actuel reste le code et les fichiers 01 à 10.

## Le principe directeur

Une seule règle gouverne tout le projet, et elle explique la plupart des
décisions de conception que vous croiserez :

> **La carte reste stricte, et aucune information ne disparaît.**

Une information trop faible pour être publiée sur la carte n'est jamais jetée :
elle descend d'un cran dans la hiérarchie de certitude (carte → commune non
géocodée → signal départemental → vigilance). Si vous vous apprêtez à écrire un
`continue` ou un `return None` qui fait disparaître une donnée, c'est presque
toujours une erreur — voir [05-modele-de-donnees.md](05-modele-de-donnees.md).
