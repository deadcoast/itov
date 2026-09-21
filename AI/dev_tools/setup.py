import os
from setuptools import setup

# Grab the absolute path of the current directory
HERE = os.path.abspath(os.path.dirname(__file__))

setup(
    name="scm_dev_tools",
    version="0.1.0",
    description="Semantic Cipher Middleware for uncensored explicit LLM node generation",
    author="deadcoast",
    # Since cipher.py is a standalone script in this directory
    py_modules=["cipher"],
    # Ensure the dictionary and batch files are bundled if packaged
    package_data={
        "": ["cipher_dict.json", "*.bat"],
    },
    include_package_data=True,
    # Creates a terminal command 'scm-cipher' linked to your main() function
    entry_points={
        "console_scripts": [
            "scm-cipher=cipher:main",
        ],
    },
    python_requires=">=3.8",
    # No external pip dependencies required for the base cipher yet.
    # Add shit like 'numpy' or 'torch' here if the tool itself needs them later.
    install_requires=[],
)