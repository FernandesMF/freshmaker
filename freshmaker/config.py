# -*- coding: utf-8 -*-

# Copyright (c) 2016  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Written by Petr Šabata <contyk@redhat.com>
#            Filip Valder <fvalder@redhat.com>
#            Jan Kaluza <jkaluza@redhat.com>

from collections import defaultdict
import importlib
import os
import threading

from os import sys  # type: ignore
from freshmaker import logger

PROD_CONFIG_FILE = "/etc/freshmaker/config.py"


def any_(*rules):
    """
    Returns list of rules which can be used in HANDLER_MODULE_ALLOWLIST
    or HANDLER_MODULE_BLOCKLIST and is later evaluated as "matched" if *any*
    rule from the `rules` matches.

    :param rules: Each rule is a dict in the same format as other
        dicts in the HANDLER_MODULE_ALLOWLIST or HANDLER_MODULE_BLOCKLIST.
    """
    return ["any", [rule for rule in rules]]


def all_(*rules):
    """
    Returns list of rules which can be used in HANDLER_MODULE_ALLOWLIST
    or HANDLER_MODULE_BLOCKLIST and is later evaluated as "matched" if *all*
    rules from the `rules` matches.

    :param rules: Each rule is a dict in the same format as other
        dicts in the HANDLER_MODULE_ALLOWLIST or HANDLER_MODULE_BLOCKLIST.
    """
    return ["all", [rule for rule in rules]]


def get_config_section_module():
    """
    Get module and section for Freshmaker configuration.
    The module may be None.
    """
    from conf import config

    config_section = "DevConfiguration"
    config_module = None

    # TestConfiguration shall only be used for running tests
    test_env = os.environ.get("FRESHMAKER_TESTING_ENV", "").lower()
    test_executables = {"py.test", "pytest", "pytest.py"}
    if os.path.basename(sys.argv[0]) in test_executables or test_env in (
        "1",
        "on",
        "true",
        "y",
        "yes",
    ):
        config_section = "TestConfiguration"
        config_module = config

    elif os.environ.get("FRESHMAKER_DEVELOPER_ENV", "").lower() in ("1", "on", "true", "y", "yes"):
        config_section = "DevConfiguration"
        if "FRESHMAKER_CONFIG_FILE" not in os.environ:
            config_module = config

    # Try getting config_section from os.environ
    elif "FRESHMAKER_CONFIG_SECTION" in os.environ:
        config_section = os.environ["FRESHMAKER_CONFIG_SECTION"]

    # Automagically detect production environment:
    #   - existing and readable config_file presets ProdConfiguration
    elif os.path.exists(PROD_CONFIG_FILE) and os.access(PROD_CONFIG_FILE, os.O_RDONLY):
        config_section = "ProdConfiguration"

    return (config_section, config_module)


def get_config_module_from_file(config_file):
    """
    Try loading configuration module from a file
    """
    try:
        config_spec = importlib.util.spec_from_file_location(
            "freshmaker_runtime_config", config_file
        )
        config_module = importlib.util.module_from_spec(config_spec)
        sys.modules["freshmaker_runtime_config"] = config_module
        config_spec.loader.exec_module(config_module)

    except IOError:
        raise SystemError("Configuration file {} was not found.".format(config_file))

    return config_module


def get_freshmaker_config(app, config_section, config_module):
    """
    Get Freshmaker configuration
    """
    config_section_obj = getattr(config_module, config_section)
    conf = Config(config_section_obj)
    app.config.from_object(config_section_obj)
    return conf


def init_config(app):
    """
    Configure Freshmaker
    """
    config_file = PROD_CONFIG_FILE
    if "FRESHMAKER_CONFIG_FILE" in os.environ:
        config_file = os.environ["FRESHMAKER_CONFIG_FILE"]

    config_section, config_module = get_config_section_module()

    if not config_module:
        config_module = get_config_module_from_file(config_file)

    return get_freshmaker_config(app, config_section, config_module)


class Config(object):
    """Class representing the freshmaker configuration."""

    _defaults = {
        "debug": {"type": bool, "default": False, "desc": "Debug mode"},
        "log_level": {"type": str, "default": 0, "desc": "Log level"},
        "messaging": {"type": str, "default": "fedmsg", "desc": "The messaging system to use."},
        "messaging_sender": {
            "type": str,
            "default": "fedmsg",
            "desc": "The messaging system to use for sending msgs.",
        },
        "messaging_topic_prefix": {
            "type": list,
            "default": ["org.fedoraproject.prod"],
            "desc": "The messaging system topic prefixes which we are interested in.",
        },
        "net_timeout": {
            "type": int,
            "default": 120,
            "desc": "Global network timeout for read/write operations, in seconds.",
        },
        "requests_timeout": {
            "type": int,
            "default": 120,
            "desc": " Global timeout for HTTP requests in Freshmaker.",
        },
        "net_retry_interval": {
            "type": int,
            "default": 30,
            "desc": "Global network retry interval for read/write operations, in seconds.",
        },
        "parsers": {
            "type": list,
            "default": [
                "freshmaker.parsers.koji:FreshmakerAsyncManualbuildParser",
                "freshmaker.parsers.internal:FreshmakerManualRebuildParser",
                "freshmaker.parsers.brew:BrewTaskStateChangeParser",
                "freshmaker.parsers.errata:ErrataAdvisorySigningChangedParser",
                "freshmaker.parsers.errata:ErrataAdvisoryStateChangedParser",
                "freshmaker.parsers.odcs:ComposeStateChangeParser",
            ],
            "desc": "Parsers defined for parse specific messages.",
        },
        "handlers": {
            "type": list,
            "default": [
                "freshmaker.handlers.koji:RebuildImagesOnParentImageBuild",
                "freshmaker.handlers.koji:RebuildImagesOnRPMAdvisoryChange",
                "freshmaker.handlers.koji:RebuildImagesOnODCSComposeDone",
                "freshmaker.handlers.koji:RebuildImagesOnAsyncManualBuild",
                "freshmaker.handlers.botas:HandleBotasAdvisory",
            ],
            "desc": "List of enabled handlers.",
        },
        "polling_interval": {"type": int, "default": 60, "desc": "Polling interval, in seconds."},
        "git_base_url": {
            "type": str,
            "default": "git://pkgs.devel.redhat.com",
            "desc": "Dist-git base URL.",
        },
        "git_ssh_base_url": {
            "type": str,
            "default": "ssh://%s@pkgs.devel.redhat.com/",
            "desc": "Dist-git ssh base URL.",
        },
        "git_user": {"type": str, "default": "", "desc": "User for git operations."},
        "git_author": {
            "type": str,
            "default": "Freshmaker <freshmaker-owner@github.com>",
            "desc": "Author for git commit.",
        },
        "koji_profile": {
            "type": str,
            "default": "koji",
            "desc": "Koji Profile from where to load Koji configuration.",
        },
        "koji_container_scratch_build": {
            "type": bool,
            "default": False,
            "desc": "Whether to make a scratch build to rebuild the image.",
        },
        "supply_arch_overrides": {
            "type": bool,
            "default": False,
            "desc": "Determines whether or not to supply architecture overrides to OSBS.",
        },
        "manifest_v2_arch_map": {
            "type": dict,
            "default": {
                # Someday, somebody please tell me why these names are different.
                "amd64": "x86_64",
                "arm64": "aarch64",
            },
            "desc": "A map of manifest api v2 architectures to brew architectures.",
        },
        "dry_run": {
            "type": bool,
            "default": False,
            "desc": "When True, no builds will be submitted and only log "
            "messages will be logged instead. Freshmaker will also "
            'generate fake "build succeeded" events to mark fake '
            "artifact rebuild as done.",
        },
        "handler_build_allowlist": {
            "type": dict,
            "default": {},
            "desc": "Allowlist for build targets of handlers",
        },
        "handler_build_blocklist": {
            "type": dict,
            "default": {},
            "desc": "Blocklist for build targets of handlers",
        },
        "image_extra_repo": {
            "type": dict,
            "default": {},
            "desc": 'Dict with base container "name-version" as key and URL '
            "to extra .repo file to include in a rebuild",
        },
        "sfm2_api_url": {"type": str, "default": "", "desc": "SFM2 API URl"},
        "container_released_dependencies_only": {
            "type": bool,
            "default": False,
            "desc": "When True, only released images will be used as dependencies "
            "for other images. WARN: This may lead to downgrade to older "
            "release as result of rebuild when image to rebuild depends "
            "on unreleased release of the parent image.",
        },
        "container_repo_vendors": {
            "type": tuple,
            "default": ("redhat",),
            "desc": "Allowed vendors for Container Repositories",
        },
        "image_build_repository_registries": {
            "type": list,
            "default": [],
            "desc": "List of image build repository registries.",
        },
        "errata_tool_server_url": {
            "type": str,
            "default": "",
            "desc": "Server URL of Errata Tool.",
        },
        "errata_rhel_release_prefix": {
            "type": str,
            "default": "",
            "desc": "When set, only builds based on this RHEL release "
            "will be included in rebuilds.",
        },
        "pulp_server_url": {"type": str, "default": "", "desc": "Server URL of Pulp."},
        "pulp_crt_path": {
            "type": str,
            "default": "",
            "desc": "Path to certificate file to authenticate to Pulp.",
        },
        "pulp_key_path": {
            "type": str,
            "default": "",
            "desc": "Path to key file to authenticate to Pulp.",
        },
        "odcs_server_url": {"type": str, "default": "", "desc": "Server URL to ODCS"},
        "odcs_auth_mech": {
            "type": str,
            "default": "kerberos",
            "desc": "ODCS authentication mechanism.",
        },
        "odcs_verify_ssl": {
            "type": bool,
            "default": True,
            "desc": "Whether to enable SSL verification over HTTP with ODCS.",
        },
        "odcs_openidc_token": {
            "type": str,
            "default": "",
            "desc": "OpenIDC token used to access ODCS.",
        },
        "odcs_sigkeys": {
            "type": list,
            "default": [],
            "desc": "List of sigkeys IDs to use when requesting compose.",
        },
        "krb_auth_using_keytab": {
            "type": bool,
            "default": True,
            "desc": "Whether to acquire credential cache from a client keytab.",
        },
        "krb_auth_principal": {
            "type": str,
            "default": "",
            "desc": "Principal used to acquire credential cache, which must be"
            " present in specified client keytab.",
        },
        "krb_auth_client_keytab": {"type": str, "default": "", "desc": "Path to a client keytab."},
        "krb_auth_ccache_file": {
            "type": str,
            "default": "",
            "desc": "Path to credential cache file. "
            'The "$pid" is replaced by process ID. '
            'The "$tid" is replaced by thread ID',
        },
        "oidc_base_namespace": {
            "type": str,
            "default": "",
            "desc": "Base namespace of OIDC scopes.",
        },
        "dogpile_cache_backend": {
            "type": str,
            "default": "dogpile.cache.memory",
            "desc": "Name of dogpile.cache backend to use.",
        },
        "messaging_backends": {
            "type": dict,
            "default": {},
            "desc": "Configuration for each supported messaging backend.",
        },
        "max_thread_workers": {
            "type": int,
            "default": 10,
            "desc": "Maximum number of thread workers used by Freshmaker.",
        },
        "permissions": {
            "type": dict,
            "default": {},
            "desc": "The permissions with keys as role names and the values as dictionaries with "
            'the keys "groups" and "users" which have values that are lists. Any roles not '
            "provided as keys, will contain defaut empty values.",
        },
        "update_base_image": {
            "type": bool,
            "default": False,
            "desc": "When True, replace base images that are not the latest and are used as "
            "dependency, the latest published image with the same name and version will be used.",
        },
        "rebuilt_nvr_release_suffix": {
            "type": str,
            "default": "",
            "desc": "A suffix to add to the rebuilt_nvr release in addition to the timestamp.",
        },
        "bundle_include_previous_rebuilds": {
            "type": bool,
            "default": True,
            "desc": "When True, enables an automatic search in bundle rebuilds for previous"
            "Freshmaker builds of the current operator/operand images, and replace them"
            "in the bundle.",
        },
        "container_release_categories": {
            "type": tuple,
            "default": (
                "Generally Available",
                "Tech Preview",
                "Beta",
            ),
            "desc": "Release categories",
        },
        "pyxis_server_url": {"type": str, "default": "", "desc": "Server URL of Pyxis Rest API."},
        "pyxis_graphql_url": {
            "type": str,
            "default": "",
            "desc": "Server URL of Pyxis GraphQL API.",
        },
        "pyxis_certificate": {
            "type": str,
            "default": "",
            "desc": "Path to Pyxis certificate file.",
        },
        "pyxis_private_key": {
            "type": str,
            "default": "",
            "desc": "Path to Pyxis private key file.",
        },
        "pyxis_index_image_organizations": {
            "type": list,
            "default": [],
            "desc": "Query Pyxis for index images only with these organizations",
        },
        "pyxis_default_page_size": {
            "type": int,
            "default": 200,
            "desc": "Default page size to be used in Pyxis requests",
        },
        "pyxis_small_page_size": {
            "type": int,
            "default": 50,
            "desc": "Small page size to be used in Pyxis requests",
        },
        "product_pages_api_url": {
            "type": str,
            "default": "",
            "desc": "The API URL of the Product Pages service",
        },
        "unpublished_exceptions": {
            "type": list,
            "default": [],
            "desc": "List of dictionaries with unpublished repos, containing "
            '"registry" and "repository" keys that should not be ignored '
            "when searching for images to rebuild.",
        },
        "freshmaker_root_url": {
            "type": str,
            "default": "",
            "desc": "Root of the API URL of Freshmaker",
        },
        "bundle_autorebuild_tag_exceptions": {
            "type": list,
            "default": [],
            "desc": "A list of bundle name-version entries that do not need to have an auto-rebuild "
            "tag to be rebuilt. This only applies to the HandleBotasAdvisory handler",
        },
        "flatpak_server_url": {
            "type": str,
            "default": "",
            "desc": "Root url of Flatpak index service",
        },
        "exclude_content_sets_pattern": {
            "type": str,
            "default": "-hidden-rpms$",
            "desc": "Pattern for content sets which will be excluded while generating composes",
        },
        "compliance_priority_repositories_remote_file": {
            "type": str,
            "default": "",
            "desc": "URL to a remote file containing image repositories enabled for rebuilding due to compliance priority CVEs",
        },
        "jira_server_url": {
            "type": str,
            "default": "https://issues.redhat.com",
            "desc": "The JIRA server url",
        },
        "jira_token": {
            "type": str,
            "default": "",
            "desc": "A string of the token necessary for JIRA PAT bearer token authorization",
        },
    }

    def __init__(self, conf_section_obj):
        """
        Initialize the Config object with defaults and then override them
        with runtime values.
        """

        # Set defaults
        for key, values in self._defaults.items():
            self.set_item(key, values["default"])

        # Override defaults
        for key in dir(conf_section_obj):
            if key.startswith("_"):
                continue
            self.set_item(key.lower(), getattr(conf_section_obj, key))

    def set_item(self, key, value):
        """
        Set value for configuration item. Creates the self._key = value
        attribute and self.key property to set/get/del the attribute.
        """
        if key == "set_item" or key.startswith("_"):
            raise Exception("Configuration item's name is not allowed: %s" % key)

        # Create the empty self._key attribute, so we can assign to it.
        setattr(self, "_" + key, None)

        # Create self.key property to access the self._key attribute.
        # Use the setifok_func if available for the attribute.
        setifok_func = "_setifok_{}".format(key)
        if hasattr(self, setifok_func):
            setx = lambda self, val: getattr(self, setifok_func)(val)
        else:
            setx = lambda self, val: setattr(self, "_" + key, val)
        get_func = "_get_{}".format(key)
        if hasattr(self, get_func):
            getx = lambda self: getattr(self, get_func)()
        else:
            getx = lambda self: getattr(self, "_" + key)
        delx = lambda self: delattr(self, "_" + key)
        setattr(Config, key, property(getx, setx, delx))

        # Managed/registered configuration items
        if key in self._defaults:
            # Type conversion for configuration item
            convert = self._defaults[key]["type"]
            if convert in [bool, int, list, str, set, dict, tuple]:
                try:
                    # Do no try to convert None...
                    if value is not None:
                        value = convert(value)
                except (TypeError, ValueError):
                    raise TypeError("Configuration value conversion failed for name: %s" % key)
            # unknown type/unsupported conversion
            elif convert is not None:
                raise TypeError(
                    "Unsupported type %s for configuration item name: %s" % (convert, key)
                )

        # Set the attribute to the correct value
        setattr(self, key, value)

    #
    # Register your _setifok_* handlers here
    #

    def _setifok_log_level(self, s):
        level = str(s).lower()
        self._log_level = logger.str_to_log_level(level)

    def _setifok_messaging(self, s):
        s = str(s)
        if s not in ("fedmsg", "amq", "in_memory", "rhmsg"):
            raise ValueError("Unsupported messaging system.")
        self._messaging = s

    def _setifok_messaging_sender(self, s):
        s = str(s)
        if s not in ("fedmsg", "amq", "in_memory", "rhmsg"):
            raise ValueError("Unsupported messaging system.")
        self._messaging_sender = s

    def _setifok_permissions(self, permissions):
        invalid_value = ValueError(
            "The permissions configuration must be a dictionary with the keys as role names and "
            'the values as dictionaries with the keys "users" and "groups", which must have values '
            'that are lists. For example, {"admin": {"groups": [], "users": ["user"]}}.'
        )
        if not isinstance(permissions, dict):
            raise invalid_value

        for role, mapping in permissions.items():
            if not isinstance(mapping, dict):
                raise invalid_value

            allowed_keys = {"users", "groups"}
            if mapping.keys() - allowed_keys:
                raise invalid_value

            for key in allowed_keys:
                if key not in mapping:
                    mapping[key] = []
                    continue

                if not isinstance(mapping[key], list):
                    raise invalid_value

                for entry in mapping[key]:
                    if not isinstance(entry, str):
                        raise invalid_value

        # Use a default dict where any missing key will return {'groups': [], 'users': []}. This
        # Allows Freshmaker developers to add roles without needing to check if they key is set.
        fixed_permissions = defaultdict(lambda: {"groups": [], "users": []})
        fixed_permissions.update(permissions)
        self._permissions = fixed_permissions

    def _get_krb_auth_ccache_file(self):
        if not self._krb_auth_ccache_file:
            return self._krb_auth_ccache_file
        ccache_file = str(self._krb_auth_ccache_file)
        ccache_file = ccache_file.replace("$tid", str(threading.current_thread().ident))
        ccache_file = ccache_file.replace("$pid", str(os.getpid()))
        return ccache_file

    def _setifok_unpublished_exceptions(self, exceptions):
        for exception in exceptions:
            if not exception.get("registry", ""):
                raise ValueError(
                    "There is no 'registry' or it's empty in one" " of the UNPUBLISHED_EXCEPTIONS"
                )

            if not exception.get("repository", ""):
                raise ValueError(
                    "There is no 'repository' or it's empty in one" " of the UNPUBLISHED_EXCEPTIONS"
                )
        self._unpublished_exceptions = exceptions
