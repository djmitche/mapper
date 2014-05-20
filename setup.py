#!/usr/bin/env python

from setuptools import setup, find_packages

setup(name='relengapi-mapper',
      version='0.3',
      description='hg to git mapper',
      author='Chris AtLee',
      author_email='chris@atlee.ca',
      url='https://github.com/petemoore/mapper',
      packages=find_packages(),
      namespace_packages=['relengapi', 'relengapi.blueprints'],
      entry_points={
          "relengapi_blueprints": [
                'mapper = relengapi.blueprints.mapper:bp',
          ],
      },
      install_requires=[
          'Flask',
          'relengapi',
          'IPy',
          'python-dateutil',
      ],
      license='MPL2',
      extras_require = {
          'test': [
              'nose',
              'mock'
          ]
      }
)
