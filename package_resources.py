#coding: utf8
#################################### IMPORTS ###################################

# Std Libs
import codecs
import functools
import glob
import os
import re
import pprint
import sys
import unittest
import zipfile

from os.path import normpath, split, join, isdir, splitext, basename, dirname
from collections import defaultdict

# Sublime Libs
import sublime
import sublime_plugin

try:         import nose
except ImportError: nose = None

################################### CONSTANTS ##################################

PREFIX_ZIP_PACKAGE_RELATIVE = re.compile("(?P<prefix>.*)/"
                                         "(?P<package>.*?)\.sublime-package/"
                                         "(?P<relative>.*)")

ST2 = sublime.version()[:1] == '2'
ST3 = not ST2

PATH_CONFIG_RELATIVE, PATH_ABSOLUTE, PATH_ZIPFILE_PSEUDO = range(3)

################################################################################
"""

Brief:

@Globbing a whole list of packages for files that match a pattern:

    - possibly in nested folders

    - @Listing contents of a Package, files of which may be spread across an
        a .sublime-package, with overrides in an actual folder in 
        sublime.packages_path()

"""
#################################### HELPERS ###################################

class bunch(dict):
    def __init__(self, *args, **kw):
        dict.__init__(self, *args, **kw)
        self.__dict__ = self

def normed_platform():
    platform = sublime.platform().title()
    if platform == 'Osx': return 'OSX'
    return platform

def zipped_package_locations():
    near_executable          = join(dirname(sublime.executable_path()),
                                    'Packages')
    return [ sublime.installed_packages_path(), near_executable]

################################# PATH HELPERS #################################

def zip_path_components(pth):
    """
    >>> d=zip_path_components(r"C:\\fuck\\fuck.sublime-package\\two.txt")
    >>> d['prefix']
    'C:/fuck'
    >>> d['relative']
    'two.txt'
    >>> d['package']
    'fuck'
    
    """
    m = PREFIX_ZIP_PACKAGE_RELATIVE.search(re.sub(r'\\', '/', pth))
    if m is not None:
        return m.groupdict()

def decompose_path(pth):
    """
    
    >>> tc = decompose_path
    >>> tc("Packages/Fool/one.py")
    ('Fool', 'one.py', 0, None)
    
    """

    if pth.startswith("Packages/"):
        _, package, relative = pth.split("/", 2)
        return package, relative, PATH_CONFIG_RELATIVE, None

    m = zip_path_components(pth)
    if m is not None:
        return m['package'], m['relative'], PATH_ZIPFILE_PSEUDO, m['prefix']
    else:
        pth = pth[len(sublime.packages_path())+1:]
        pkg, relative = pth.split("/", 1)
        return pkg, relative, PATH_ABSOLUTE, sublime.packages_path()

def open_file_path(fn):
    """
    Formats a path as /C/some/path/on/windows/no/colon.txt that is suitable to
    be passed as the `file` arg to the `open_file` command.
    """
    fn = normpath(fn)
    fn = re.sub('^([a-zA-Z]):', '/\\1', fn)
    fn = re.sub(r'\\', '/', fn)
    return fn

def normalise_to_open_file_path(file_name):
    """
    
    >>> pth = '/Packages/Vintage.sublime-package/Default (Linux).sublime-keymap'
    >>> normalise_to_open_file_path(pth)
    '${packages}/Vintage/Default (Linux).sublime-keymap'
    
    :file_name:
    
        A str that could actually be a pseudo path to a file nested inside a
        `sublime-package` file or 
    
    The command `open_file` has magic to open file contained in zip files, or in
    extracted folder overrides.
    
    """

    pkg, relative, pth_type, _ = decompose_path(file_name)
    return ( open_file_path(file_name) if pth_type is PATH_ABSOLUTE else
             "${packages}/%s/%s" % (pkg, relative) )

############################ PACKAGE_FILE_* HELPERS ############################

def _package_file_helper(fn, encoding='utf-8', only_exists=False):
    pkg, path, pth_type, _ = decompose_path(fn)

    if pth_type == PATH_CONFIG_RELATIVE:
        pkg_path = os.path.join(sublime.packages_path(), pkg)
        abs_fn = os.path.join(pkg_path, path)
    else:
        abs_fn = fn

    if os.path.exists(abs_fn):
        if only_exists:
            return True
        else:
            if encoding is None: kw = dict(mode='rb')
            else:                kw = dict(mode='rU', encoding=encoding)

            with codecs.open(abs_fn, **kw) as fh:
                return fh.read()

    for base_pth in zipped_package_locations():
        zip_path = os.path.join(base_pth, pkg + '.sublime-package')
        if not os.path.exists(zip_path): continue

        with zipfile.ZipFile(zip_path, 'r') as zh:
            if path in zh.namelist():
                if only_exists:
                    return True
                else:
                    text = bytes= zh.read(path)
                    if encoding:
                        text = bytes.decode('utf-8')
                    return text

def package_partial(**kw):
    return functools.partial(_package_file_helper, **kw)

package_file_exists = package_partial(only_exists=True)
package_file_contents = _package_file_helper
package_file_binary_contents = package_partial(encoding=None)

########################## PACKAGE LISTING / GLOBBING ##########################

def enumerate_virtual_package_folders():
    """
    
    Note that a package may appear more than once in this list.
    
    An abstract Package consist of a sublime-package sitting in one of the 
    `zipped_package_locations()` and also various overrides in a folder 
    on `sublime.packages_path()`
    
    """
    installed_packages       = ([

            # We make redundant info here, so later we know this
            bunch( zip_path    = False,
                   folder_path = join(sublime.packages_path(), d),
                   pkg_name    = d )
        for
            d in os.listdir(sublime.packages_path())
        if
            isdir (join(sublime.packages_path(), d))
    ])

    for location in zipped_package_locations():
        packages_pattern = location + '/*.sublime-package'
        packages = glob.glob(packages_pattern)

        for package in packages:
            package_info = bunch (
                folder_path=False,
                zip_path=package,
                pkg_name=basename(splitext(package)[0]))
            installed_packages.append(package_info)

    return installed_packages

def create_virtual_package_lookup():
    """
    :return:
        A dict of {pkg_name : {zip_path: '', folder_path: '', pkg_name : ''}}
        
        ie.  {pkg_name : merged_package_info}
    """
    mapping = defaultdict(bunch)
    packages = enumerate_virtual_package_folders()

    for package in packages:
        pkg = mapping[package.pkg_name]

        pkg.pkg_name  = package.pkg_name
        pkg.zip_path     = pkg.get("zip") or package.zip_path
        pkg.folder_path  = pkg.get("folder") or package.folder_path

    return dict(mapping)

def list_virtual_package_folder(merged_package_info, matcher=None):
    zip_file = merged_package_info['zip_path']
    folder = merged_package_info['folder_path']
    zip_files = []

    if zip_file:
        with  zipfile.ZipFile(zip_file, 'r') as z:
            zip_files = sorted (z.namelist())

    contents = defaultdict(lambda: bunch( relative_name = None,
                                          zip_path=False,
                                          folder_path=False ))
    for f in zip_files:
        if matcher is not None:
            if not matcher(f):
                continue
        
        f_info = contents[f]
        f_info.relative_name = f
        f_info.zip_path = os.path.join(zip_file, f)

    if folder:
        for root, dirnames, filenames in os.walk(folder):
            for i in range(len(dirnames)-1, -1, -1):
                if dirnames[i] in ('.svn', '.git', '.hg'):
                    del dirnames[i]

            for f in filenames:
                relative_name = os.path.join(root[len(folder) + 1:], f)
                f_info = contents[relative_name]
                f_info.relative_name  = relative_name
                f_info.folder_path  = os.path.join(root, f)

    return contents

##################################### TESTS ####################################

class Tests(unittest.TestCase):
    """
    
    These tests are pretty vague, but at least exercise the code somewhat
    
    """
    def test_enumerate_virtual_package_folders(self):
        enumerate_virtual_package_folders()

    def test_create_virtual_package_lookup(self):
        create_virtual_package_lookup()

    def test_list_virtual_package_folder(self):
        lookup = create_virtual_package_lookup()
        (list_virtual_package_folder(lookup['Java']))
        (list_virtual_package_folder(lookup['User']))

    def test_package_file_exists(self):
        self.assertTrue(package_file_exists("Packages/Default/sort.py"))

    def test_package_file_contents(self):
        (package_file_contents (
                "Packages/PackageResources/package_resources.py"))

        ars = package_file_contents("Packages/Default/sort.py")

        text="""\
def permute_selection(f, v, e):
    regions = [s for s in v.sel() if not s.empty()]
    regions.sort()"""

        self.assertIn(text, ars)

        if ST3:
            self.assertTrue(isinstance(ars, str))
        else:
            self.assertTrue(isinstance(ars, unicode))

    def test_package_file_binary_contents(self):
        ars = package_file_binary_contents("Packages/Default/sort.py")

        if ST3:
            self.assertTrue(isinstance(ars, bytes))
        else:
            self.assertTrue(isinstance(ars, str))

    def test_decompose_path(self):
        tc = decompose_path
        aseq = self.assertEquals

        r1 = (tc("Packages/Fool/one.py"))
        r2 = (tc("/Packages/Default.sublime-package/nested/sort.py"))
        r3 = (tc(sublime.packages_path() + "/Package/Nested/asset.pth"))

        aseq(r1, ('Fool', 'one.py',              PATH_CONFIG_RELATIVE, None))
        aseq(r2, ('Default', 'nested/sort.py',   PATH_ZIPFILE_PSEUDO, '/Packages'))
        aseq(r3, ('Package', 'Nested/asset.pth', PATH_ABSOLUTE, sublime.packages_path()))

################ ONLY LOAD TESTS WHEN DEVELOPING NOT ON START UP ###############

try:               times_module_has_been_reloaded  += 1
except NameError:  times_module_has_been_reloaded  =  0       #<em>re</em>loaded

if times_module_has_been_reloaded:
    target = __name__

    if nose:
        nose.run(argv=[ 'sys.executable', target, '--with-doctest', '-s' ])
    else:
        suite = unittest.TestLoader().loadTestsFromName(target)
        unittest.TextTestRunner(stream = sys.stdout,  verbosity=0).run(suite)

    print ("running tests", target)
    print ('\nReloads: %s' % times_module_has_been_reloaded)

################################################################################