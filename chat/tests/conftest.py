import os


# Settings is instantiated during test collection, before fixtures run.
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5432/test"
os.environ["JWT_SECRET"] = "test-secret-at-least-32-bytes-long"
