# init_db.py
import sys
from database import init_db, seed_db

def main():
    print("Initializing CricScorer database...")
    init_db()
    print("Database tables created successfully.")
    
    print("Seeding database with default players, teams, and tournament...")
    seed_db()
    print("Database seeded successfully.")

if __name__ == "__main__":
    main()
