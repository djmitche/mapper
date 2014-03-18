mapper
======

mapper is a small web app that will give you the corresponding revision for a given git or hg revision in a project.  It also serves full mapfiles, full combined mapfiles, full mapfiles since datetime, or full combined mapfiles since datetime.

It is built as a [RelengAPI](https://wiki.mozilla.org/ReleaseEngineering/Applications/RelengAPI) component.

## Prerequisites

    * RelengAPI
    * IPy

## Testing

Testing needs a few more packages.
Install with the 'test' extra to pull in those packages.
For development purposes:

    pip install -e .[test]

Or to install from pypi:

    pip install relengapi-mapper[test]
