def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: uses real embedded Qdrant / models; may skip if DB locked"
    )
