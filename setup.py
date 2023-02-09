#!/usr/bin/env python

"""The setup script."""

from setuptools import setup, find_packages

with open('README.rst') as readme_file:
    readme = readme_file.read()

with open('HISTORY.rst') as history_file:
    history = history_file.read()

requirements = ['Click>=7.0', 'Jinja2==2.11.1', 'markupsafe==2.0.1',
                'markdown2==2.3.8', 'uuid==1.30', 'verboselogs==1.7']

test_requirements = []

setup(
    author="Jingcheng Yang",
    author_email='yjcyxky@163.com',
    python_requires='>=3.6',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
    ],
    description="A utility for cooperating with biominer app.",
    entry_points={
        'console_scripts': [
            'biominer-app-util=biominer_app_util.cli:main',
            'app-utility=biominer_app_util.cli:main',
        ],
    },
    install_requires=requirements,
    license="MIT license",
    long_description=readme + '\n\n' + history,
    include_package_data=True,
    keywords='biominer_app_util',
    name='biominer_app_util',
    packages=find_packages(
        include=['biominer_app_util', 'biominer_app_util.*']),
    test_suite='tests',
    tests_require=test_requirements,
    url='https://github.com/yjcyxky/biominer_app_util',
    version='0.1.0',
    zip_safe=False,
)
