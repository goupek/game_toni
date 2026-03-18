from db_queries import get_user_word_progress

rows = get_user_word_progress()

print("Rows:", len(rows))
for row in rows[:10]:
    print(row)