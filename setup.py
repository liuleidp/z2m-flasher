#!/usr/bin/env python
"""z2mflasher setup script."""
from setuptools import setup, find_packages

from z2mflasher import const

PROJECT_NAME = 'z2mflasher'
PROJECT_PACKAGE_NAME = 'z2mflasher'
PROJECT_LICENSE = 'MIT'
PROJECT_AUTHOR = 'ESPHome, SchumyHao'
PROJECT_COPYRIGHT = '2019, ESPHome'
PROJECT_EMAIL = 'schumyhaojl@126.com'

PROJECT_GITHUB_USERNAME = 'smarthomefans'
PROJECT_GITHUB_REPOSITORY = 'z2m-flasher'

PYPI_URL = 'https://pypi.python.org/pypi/{}'.format(PROJECT_PACKAGE_NAME)
GITHUB_PATH = '{}/{}'.format(PROJECT_GITHUB_USERNAME, PROJECT_GITHUB_REPOSITORY)
GITHUB_URL = 'https://github.com/{}'.format(GITHUB_PATH)

DOWNLOAD_URL = '{}/archive/{}.zip'.format(GITHUB_URL, const.__version__)

REQUIRES = [
    'wxpython>=4.0,<5.0',
    'esptool==2.8',
    'requests>=2.0,<3',
    'pyserial==3.0.1',
    'platformio==4.1.0',
]

setup(
    name=PROJECT_PACKAGE_NAME,
    version=const.__version__,
    license=PROJECT_LICENSE,
    url=GITHUB_URL,
    download_url=DOWNLOAD_URL,
    author=PROJECT_AUTHOR,
    author_email=PROJECT_EMAIL,
    description="ESP8266/ESP32 firmware flasher for z2m module",
    include_package_data=True,
    zip_safe=False,
    platforms='any',
    test_suite='tests',
    python_requires='>=3.5',
    install_requires=REQUIRES,
    keywords=['home', 'automation'],
    entry_points={
        'console_scripts': [
            'z2mflasher = z2mflasher.__main__:main'
        ]
    },
    packages=find_packages()
)
