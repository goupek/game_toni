from db_queries import get_topics_with_words

data = get_topics_with_words()

print("Number of topics:", len(data["topics"]))
for topic in data["topics"]:
    print(topic)