#!/usr/bin/env python3
"""
Script to clear all workers from the render farm database.
"""

from database import clear_all_workers

if __name__ == "__main__":
    print("Clearing all workers from the database...")
    clear_all_workers()
    print("All workers have been cleared from the database.")
