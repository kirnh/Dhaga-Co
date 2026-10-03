import os

# Set before main.py is imported. Fake values: tests never reach Sarvam.
os.environ["APP_PASSWORD"] = "test-password"
os.environ["SARVAM_API_KEY"] = "sk_test_not_a_real_key"
