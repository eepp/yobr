# Copyright (c) 2020 Philippe Proulx <eepp.ca>
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
# CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import enum
import json
import os
import os.path
import subprocess
import logging
import yobr.utils


_logger = logging.getLogger(__name__)


# package information base (no build information in this)
class PkgInfo:
    def __init__(self, name, is_virtual, version, licenses,
                 dl_dir, dependencies):
        self._name = name
        self._is_virtual = is_virtual
        self._version = version
        self._licenses = licenses
        self._dl_dir = dl_dir
        self._dependencies = dependencies

    @property
    def name(self):
        return self._name

    @property
    def is_virtual(self):
        return self._is_virtual

    @property
    def version(self):
        return self._version

    @property
    def licenses(self):
        return self._licenses

    @property
    def dl_dir(self):
        return self._dl_dir

    @property
    def dependencies(self):
        return self._dependencies

    def __hash__(self):
        return hash(self._name)

    def __eq__(self, other):
        if type(other) is not type(self):
            return False

        return self._name == other._name


# target package information
class TargetPkgInfo(PkgInfo):
    def __init__(self, name, is_virtual, version, licenses, dl_dir,
                 install_target, install_staging, install_images, dependencies):
        super().__init__(name, is_virtual, version, licenses,
                         dl_dir, dependencies)
        self._install_target = install_target
        self._install_staging = install_staging
        self._install_images = install_images

    @property
    def install_target(self):
        return self._install_target

    @property
    def install_staging(self):
        return self._install_staging

    @property
    def install_images(self):
        return self._install_images

    @property
    def is_installable(self):
        return any((self._install_target, self._install_staging, self._install_images))

    @property
    def type_name(self):
        return 'target'


# host package information
class HostPkgInfo(PkgInfo):
    @property
    def type_name(self):
        return 'host'

    @property
    def is_installable(self):
        return True


def _get_br_pkg_info_entry(br_pkg_info, name, pytype, is_opt=True,
                           default=None):
    if name not in br_pkg_info:
        if not is_opt:
            raise ValueError('missing `{}` entry'.format(name))

        return default

    entry = br_pkg_info[name]

    if type(entry) is not pytype:
        raise TypeError('wrong `{}` entry type: `{}`'.format(name,
                                                             entry.__class__.__name__))

    return entry


# creates a package information object from the Buildroot `show-info`
# package info `br_pkg_info` for the package named `name`
def pkg_info_from_br_pkg_info(br_pkg_info, name):
    is_virtual = _get_br_pkg_info_entry(br_pkg_info, 'virtual', bool,
                                        default=False)
    version = _get_br_pkg_info_entry(br_pkg_info, 'version', str)

    if version == '':
        version = None

    licenses = _get_br_pkg_info_entry(br_pkg_info, 'licenses', str)
    dl_dir = _get_br_pkg_info_entry(br_pkg_info, 'dl_dir', str)
    type_str = _get_br_pkg_info_entry(br_pkg_info, 'type', str, is_opt=False)

    if type_str == 'target':
        install_target = _get_br_pkg_info_entry(br_pkg_info, 'install_target',
                                                bool, default=False)
        install_staging = _get_br_pkg_info_entry(br_pkg_info, 'install_staging',
                                                 bool, default=False)
        install_images = _get_br_pkg_info_entry(br_pkg_info, 'install_images',
                                                bool, default=False)
        return TargetPkgInfo(name, is_virtual, version, licenses, dl_dir,
                             install_target, install_staging, install_images,
                             set())
    elif type_str == 'host':
        return HostPkgInfo(name, is_virtual, version, licenses, dl_dir, set())
    else:
        raise ValueError('unknown `type` entry value: `{}`'.format(type_str))


# creates a dictionary of package names to package information objects
# from the whole Buildroot `show-info` output (as objects, not JSON)
def pkg_infos_from_br_info(br_info):
    pkg_infos = {}

    for name, br_pkg_info in br_info.items():
        # skip skeleton packages: they're boring to monitor
        if name.startswith('skeleton') or name.startswith('host-skeleton'):
            continue

        # skip root FS packages: also boring to monitor
        if br_pkg_info['type'] == 'rootfs':
            continue

        try:
            pkg_infos[name] = pkg_info_from_br_pkg_info(br_pkg_info, name)
        except Exception as exc:
            # append package name to exception's message
            raise type(exc)('`{}` package: {}'.format(name, exc)) from exc

    # update dependencies: now that we have all the package information
    # objects, use them as dependencies instead of just their name
    for pkg_info in pkg_infos.values():
        br_pkg_info = br_info[pkg_info.name]
        dep_names = _get_br_pkg_info_entry(br_pkg_info, 'dependencies', list,
                                           default=[])

        for dep_name in dep_names:
            if dep_name not in pkg_infos:
                # we don't have a package information for this dependency
                continue

            pkg_info.dependencies.add(pkg_infos[dep_name])

    return pkg_infos


def pkg_infos_from_make(br_root_dir):
    cmd = 'make -s --no-print-directory show-info'
    _logger.info('Running `{}` (in `{}`).'.format(cmd, br_root_dir))

    # make `show-info` prints information about all the configured
    # packages as a JSON object
    output = subprocess.check_output(cmd, shell=True, cwd=br_root_dir)
    _logger.info('Ran `{}`.'.format(cmd))
    return pkg_infos_from_br_info(json.loads(output))


# the stages of a package build process
@enum.unique
class PkgBuildStage(enum.Enum):
    UNKNOWN = 'unknown'
    DOWNLOADED = 'downloaded'
    EXTRACTED = 'extracted'
    PATCHED = 'patched'
    CONFIGURED = 'configured'
    BUILT = 'built'
    INSTALLED = 'installed'


# a package build
class PkgBuild:
    _STAMP_FILE_PREFIX = '.stamp_'

    def __init__(self, info, br_build_dir):
        self._info = info
        pkg_dir = info.name
        self._logger = yobr.utils._get_obj_logger(self, info.name)

        if info.version is not None:
            pkg_dir += '-{}'.format(info.version)

        self._build_dir = os.path.join(br_build_dir, pkg_dir)
        self._logger.debug('Created: build directory is `{}`.'.format(self._build_dir))

    @property
    def info(self):
        return self._info

    @property
    def build_dir(self):
        return self._build_dir

    # set of current stamps (without the `.stamp_` prefix)
    @property
    def stamps(self):
        stamps = set()

        if os.path.isdir(self._build_dir):
            for file in os.listdir(self._build_dir):
                if file.startswith(PkgBuild._STAMP_FILE_PREFIX):
                    stamps.add(file.replace(PkgBuild._STAMP_FILE_PREFIX, ''))

        return stamps

    # `True` if this package build has a stamp named `name` (without
    # the `.stamp_` prefix)
    def has_stamp(self, name):
        stamp_file = PkgBuild._STAMP_FILE_PREFIX + name
        path = os.path.join(self._build_dir, stamp_file)
        self._logger.debug('Checking if  `{}` exists.'.format(path))
        return os.path.exists(path)

    @property
    def is_downloaded(self):
        return self.has_stamp('downloaded')

    @property
    def is_extracted(self):
        return self.has_stamp('extracted')

    @property
    def is_patched(self):
        return self.has_stamp('patched')

    @property
    def is_configured(self):
        return self.has_stamp('configured')

    @property
    def is_built(self):
        return self.has_stamp('built')

    @property
    def is_installed(self):
        if type(self._info) is TargetPkgInfo:
            if self._info.install_target and self.has_stamp('target_installed'):
                return True

            if self._info.install_staging and self.has_stamp('staging_installed'):
                return True

            if self._info.install_images and self.has_stamp('images_installed'):
                return True
        elif type(self._info) is HostPkgInfo:
            if self.has_stamp('host_installed'):
                return True

        return False

    # current (latest) build stage for this package build
    @property
    def stage(self):
        if self.is_installed:
            return PkgBuildStage.INSTALLED
        elif self.is_built:
            return PkgBuildStage.BUILT
        elif self.is_configured:
            return PkgBuildStage.CONFIGURED
        elif self.is_patched:
            return PkgBuildStage.PATCHED
        elif self.is_extracted:
            return PkgBuildStage.EXTRACTED
        elif self.is_downloaded:
            return PkgBuildStage.DOWNLOADED

        return PkgBuildStage.UNKNOWN

    def __hash__(self):
        return hash(self._info)

    def __eq__(self, other):
        if type(other) is not type(self):
            return False

        return self._info == other._info


# creates a dictionary of package names to package build objects,
# running `make` to get the configured package information
def pkg_builds_from_make(br_root_dir, br_build_dir):
    pkg_infos = pkg_infos_from_make(br_root_dir)
    pkg_builds = {}

    for pkg_info in pkg_infos.values():
        pkg_builds[pkg_info.name] = PkgBuild(pkg_info, br_build_dir)

    return pkg_builds


# a monitor of package builds which caches their stages
class PkgBuildMonitor:
    def __init__(self, pkg_builds):
        self.pkg_builds = pkg_builds

    @property
    def pkg_builds(self):
        return self._pkg_builds

    @pkg_builds.setter
    def pkg_builds(self, pkg_builds):
        self._pkg_builds = pkg_builds
        self._stages = {n: PkgBuildStage.UNKNOWN for n in pkg_builds}

    # cached stage for the package build object `pkg_build`
    def stage(self, pkg_build):
        return self._stages[pkg_build.info.name]

    # update the cached build stages of all the monitored package builds
    def update(self):
        for pkg_build in self._pkg_builds.values():
            self._stages[pkg_build.info.name] = pkg_build.stage

    # cached count of built packages
    @property
    def built_count(self):
        count = 0

        for pkg_build in self._pkg_builds.values():
            if self.stage(pkg_build) in (PkgBuildStage.BUILT, PkgBuildStage.INSTALLED):
                count += 1

        return count

    # cached count of installed packages
    @property
    def installed_count(self):
        count = 0

        for pkg_build in self._pkg_builds.values():
            if self.stage(pkg_build) == PkgBuildStage.INSTALLED:
                count += 1

        return count


# creates a package build monitor, running `make` to get the configured
# package information
def pkg_build_monitor_from_make(br_root_dir, br_build_dir):
    return PkgBuildMonitor(pkg_builds_from_make(br_root_dir, br_build_dir))
