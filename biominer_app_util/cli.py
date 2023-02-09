#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
  render-app
  ~~~~~~~~~~

  App Utility.

  :copyright: © 2019 by the Jingcheng Yang.
  :license: AGPL, see LICENSE.md for more details.
"""

import verboselogs
import logging
import zipfile
import tempfile
import shutil
import uuid
import csv
import re
import sys
import json
import os
import click
from subprocess import Popen, PIPE
from markdown2 import Markdown
from jinja2 import Environment, FileSystemLoader, meta
from json.decoder import JSONDecodeError
from io import StringIO

logging.setLoggerClass(verboselogs.VerboseLogger)
logger = logging.getLogger('app-utility')

VERSION = 'v0.1.0'
APP_IS_INSTALLED = 1
APP_INSTALL_FAILED = 2
JSON_NOT_VALID = 3

DEFAULT_APP_ROOT_DIR = os.path.expanduser('~/.biominer/apps')
DEFAULT_PROJECT_ROOT_DIR = os.path.expanduser('~/.biominer/projects')


class NotFoundApp(Exception):
    pass


class InValidApp(Exception):
    pass


class AppInstallationFailed(Exception):
    pass


class AppUnInstallationFailed(Exception):
    pass


class AppDefaultVar:
    def __init__(self, app_path):
        self.app_path = app_path
        self.default = os.path.join(self.app_path, 'defaults')
        self.default_vars = self._parse()

    def _parse(self):
        if os.path.isfile(self.default):
            with open(self.default, 'r') as f:
                vars = json.load(f)
                return vars
        else:
            return dict()

    def get(self, key):
        return self.default_vars.get(key)

    def has_key(self, key):
        if self.default_vars.get(key):
            return True
        else:
            return False

    def diff(self, key_list):
        keys = self.default_vars.keys()
        # key_list need to have more key.
        diff_sets = set(key_list) - set(keys)
        return diff_sets

    def set_default_value(self, key, value):
        self.default_vars.update({key: value})

    def set_default_vars(self, vars_dict):
        self.default_vars.update(vars_dict)

    def get_default_vars(self, key_list):
        keys = self.default_vars.keys()
        inter_keys = list(set(key_list).intersection(set(keys)))
        return inter_keys

    def show_default_value(self, key_list=list()):
        if len(key_list) > 0:
            inter_keys = self.get_default_vars(key_list)
        else:
            inter_keys = self.default_vars.keys()

        results = dict()
        for key in inter_keys:
            results.update({
                key: self.get(key)
            })

        return results

    def save(self):
        with open(self.default, 'w') as f:
            json.dump(self.default_vars, f, indent=2, sort_keys=True)


def is_valid_app(path, ignore_error=False):
    """Validate a directory path and verify the directory is an valid app directory. # noqa

    :param path: Path to a directory.
    :return: The path if it exists and is an app directory, otherwise raises an error. # noqa
    """
    inputs_path = os.path.join(path, 'inputs')
    wdl_path = os.path.join(path, 'workflow.wdl')
    dependencies = os.path.join(path, 'tasks')
    pathlist = [path, inputs_path, wdl_path, dependencies]
    for fpath in pathlist:
        if not os.path.exists(fpath):
            if ignore_error:
                return False
            else:
                raise InValidApp("%s is not a valid app.\n" %
                                 os.path.basename(path))
    return True


def parse_app_name(app_name):
    pattern = r'^([-\w]+)/([-\w]+)(:[-.\w]+)?$'
    match = re.search(pattern, app_name)
    if match:
        namespace, app_name, version = match.groups()
        if version:
            version = version.strip(':')
        else:
            version = 'latest'

        return {
            "namespace": namespace,
            "app_name": app_name,
            "version": version
        }
    else:
        return False


def dfs_get_zip_file(input_path, result):
    files = os.listdir(input_path)
    for file in files:
        filepath = os.path.join(input_path, file)
        if os.path.isdir(filepath):
            dfs_get_zip_file(filepath, result)
        else:
            result.append(filepath)


def zip_path(input_path, output_path):
    f = zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED)
    filelists = []
    dfs_get_zip_file(input_path, filelists)
    for file in filelists:
        f.write(file)
    f.close()
    return output_path


def zip_path_by_ext_program(input_path, output_path):
    cmd = ['zip', '-r', '-q', output_path, input_path]
    logger.debug('ZIP: Working Directory %s, CMD: %s' % (os.getcwd(), cmd))
    proc = Popen(cmd, stdin=PIPE)
    proc.communicate()


def check_cmd(command):
    for cmdpath in os.environ['PATH'].split(':'):
        if os.path.isdir(cmdpath) and command in os.listdir(cmdpath):
            return True

    return False


def generate_dependencies_zip(dependencies_path):
    # Fix Bug: When Changing Directory, you need a abs path.
    dependencies_path = os.path.abspath(dependencies_path)
    previous_workdir = os.getcwd()
    par_dir = tempfile.mkdtemp()
    zip_output = os.path.join(par_dir, 'tasks.zip')

    os.chdir(par_dir)
    dest_path = 'tasks'
    shutil.copytree(dependencies_path, dest_path)

    # 外部命令
    if check_cmd('zip'):
        zip_path_by_ext_program('tasks', zip_output)
    else:
        # TODO: Fix the Bug
        # Python zipfile generate a zip that are version 2.0;
        # But Cromwell need a zip that are version 1.0;
        zip_path(dest_path, zip_output)

    os.chdir(previous_workdir)
    return zip_output


def install_app_by_git(base_url, namespace, app_name, dest_dir='./',
                       version='', username=None, password=None,
                       is_terminal=True):
    from urllib.parse import quote_plus
    repo_url = "%s/%s/%s.git" % (base_url.strip('http://'),
                                 namespace, app_name)
    # Fix bug: username with @
    # Need to URL encode the @ as %40: https://stackoverflow.com/a/38199336
    # Urlencode a string: https://stackoverflow.com/a/9345102
    auth_repo_url = "http://%s@%s" % (quote_plus(username), repo_url)
    version = version if version != 'latest' else 'master'
    # How to clone a specific tag with git: https://stackoverflow.com/a/31666461
    cmd = ['git', 'clone', '-b', version, '--single-branch', '-q',
           '--progress', '--depth', '1', auth_repo_url, dest_dir]
    logger.debug('Git Repo Cmd: %s' % ' '.join(cmd))
    proc = Popen(cmd, stdin=PIPE)
    password = str.encode(password)
    proc.communicate(password)
    rc = proc.returncode
    if rc == 0:
        try:
            is_valid_app(dest_dir)
            logger.success("Install %s successfully." % app_name)
            msg = "Install %s successfully." % app_name
            failed = False
        except Exception as err:
            shutil.rmtree(dest_dir)
            logger.critical(str(err))
            msg = str(err)
            failed = True
    else:
        if os.path.exists(dest_dir):
            msg = 'The app already exists.'
            failed = True
        else:
            msg = 'Unkown error, Please retry later. Maybe not found or network error.'
            failed = True

    if failed:
        logger.critical("Install %s unsuccessfully." % app_name)
        if is_terminal:
            sys.exit(APP_INSTALL_FAILED)
        else:
            raise AppInstallationFailed(msg)
    else:
        return msg


def install_app(app_root_dir, choppy_app, base_url, username, password, is_terminal=True):
    parsed_dict = parse_app_name(choppy_app)
    if parsed_dict:
        namespace = parsed_dict.get('namespace')
        app_name = parsed_dict.get('app_name')
        version = parsed_dict.get('version')
        app_dir_version = os.path.join(
            app_root_dir, "%s/%s-%s" % (namespace, app_name, version))
        install_app_by_git(base_url, namespace, app_name, version=version,
                           dest_dir=app_dir_version, username=username,
                           password=password, is_terminal=is_terminal)
    else:
        app_name = os.path.splitext(os.path.basename(choppy_app))[0]
        dest_namelist = [os.path.join(app_name, 'inputs'),
                         os.path.join(app_name, 'workflow.wdl')]

        tasks_dirpath = os.path.join(app_name, 'tasks')
        choppy_app_handler = zipfile.ZipFile(choppy_app)
        namelist = choppy_app_handler.namelist()

        # Only wdl files.
        tasks_namelist = [name for name in namelist
                          if re.match('%s/.*.wdl$' % tasks_dirpath, name)]
        dest_namelist.extend(tasks_namelist)

        def check_app(dest_namelist, namelist):
            for file in dest_namelist:
                if file in namelist:
                    continue
                else:
                    return False
            return True

        if check_app(dest_namelist, namelist):
            choppy_app_handler.extractall(app_root_dir, dest_namelist)
            logger.success("Install %s successfully." % app_name)
        else:
            raise InValidApp("Not a valid app.")


def uninstall_app(base_dir, app_name, is_terminal=True):
    if app_name not in listapps(base_dir):
        msg = 'No such app: %s' % app_name
        logger.error(msg)
        raise AppUnInstallationFailed(msg)

    app_dir = os.path.join(base_dir, app_name)

    if is_terminal:
        answer = ''
        while answer.upper() not in ("YES", "NO", "Y", "N"):
            answer = input("Enter Yes/No: ")

            answer = answer.upper()
            if answer == "YES" or answer == "Y":
                shutil.rmtree(app_dir)
                logger.success("Uninstall %s successfully." %
                               os.path.basename(app_dir))
            elif answer == "NO" or answer == "N":
                logger.warning("Cancel uninstall %s." %
                               os.path.basename(app_dir))
            else:
                logger.info("Please enter Yes/No.")
    else:
        shutil.rmtree(app_dir)
        msg = "Uninstall %s successfully." % os.path.basename(app_dir)
        logger.success(msg)
        return msg


def parse_samples(file):
    """
    TODO: may be not working.
    """
    try:
        dict_list = json.load(open(file, 'r'))
        if type(dict_list) == dict:
            dict_list = [dict_list, ]
    except Exception:
        reader = csv.DictReader(open(file, 'rt'))
        dict_list = []

        for line in reader:
            header = line.keys()
            if None in header or "" in header:
                print("CSV file is not qualified.")
                sys.exit(2)
            dict_list.append(line)

    return dict_list


def render_app(app_path, template_file, data):
    env = Environment(loader=FileSystemLoader(app_path))
    template = env.get_template(template_file)
    return template.render(**data)


def read_file_as_string(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            return f.read()
    else:
        return ''


def write_string_as_file(filepath, string):
    with open(filepath, 'w') as f:
        f.write(string)


def render_readme(app_path, app_name, readme="README.md",
                  format="html", output=None):
    readme_path = os.path.join(app_path, app_name, readme)
    if os.path.exists(readme_path):
        if format.lower() == 'html':
            markdown_text = read_file_as_string(readme_path)
            markdowner = Markdown()
            html = markdowner.convert(markdown_text)
            if output:
                write_string_as_file(output, html)
                return 'Save manual to %s' % output
            else:
                return html
        else:
            markdown_text = read_file_as_string(readme_path)
            if output:
                write_string_as_file(output, markdown_text)
                return 'Save manual to %s' % output
            else:
                return markdown_text
    else:
        return 'No manual entry for %s' % app_name


def listapps(app_root_dir):
    apps = []
    if os.path.isdir(app_root_dir):
        # backwards compatibility:
        # 1. No owner name as a namespace.
        # 2. User owner name as a namespace.
        for dir in os.listdir(app_root_dir):
            abs_dir = os.path.join(app_root_dir, dir)
            if not os.path.isdir(abs_dir):
                continue

            if is_valid_app(abs_dir, ignore_error=True):
                apps.append(dir)
            else:
                for subdir in os.listdir(abs_dir):
                    abs_dir_subdir = os.path.join(abs_dir, subdir)
                    if is_valid_app(abs_dir_subdir, ignore_error=True):
                        apps.append('%s/%s' % (dir, subdir))
    return apps


def get_header(file):
    reader = csv.DictReader(open(file, 'rb'))

    return reader.fieldnames


def write(path, filename, data):
    with open(os.path.join(path, filename), 'w') as f:
        f.write(data)


def kv_list_to_dict(kv_list):
    """Converts a list of kv pairs delimited with colon into a dictionary.

    :param kv_list: kv list: ex ['a:b', 'c:d', 'e:f']
    :return: a dict, ex: {'a': 'b', 'c': 'd', 'e': 'f'}
    """
    new_dict = dict()
    if kv_list:
        for item in kv_list:
            (key, val) = item.split(':')
            new_dict[key] = val
        return new_dict
    else:
        return None


def parse_json(instance):
    if isinstance(instance, dict):
        for key, value in instance.items():
            # str is not supported by python2.7+
            # basestring is not supported by python3+
            if isinstance(value, basestring):
                try:
                    instance[key] = json.loads(value)
                except ValueError:
                    pass
            elif isinstance(value, dict):
                instance[key] = parse_json(instance[key])
    elif isinstance(instance, list):
        for idx, value in enumerate(instance):
            instance[idx] = parse_json(value)

    return instance


def get_all_variables(app_dir, no_default=False):
    inputs_variables = get_vars_from_app(
        app_dir, 'inputs', no_default=no_default)
    workflow_variables = get_vars_from_app(
        app_dir, 'workflow.wdl', no_default=no_default)
    variables = list(set(list(inputs_variables) +
                         list(workflow_variables) + ['sample_id', ]))
    if 'project_name' in variables:
        variables.remove('project_name')

    return variables


def get_vars_from_app(app_path, template_file, no_default=False):
    env = Environment()
    template = os.path.join(app_path, template_file)
    with open(template) as f:
        templ_str = f.read()
        ast = env.parse(templ_str)
        variables = meta.find_undeclared_variables(ast)

        if no_default:
            app_default_var = AppDefaultVar(app_path)
            diff_variables = app_default_var.diff(variables)
            return diff_variables

    return variables


def check_variables(app_path, template_file, line_dict=None, header_list=None,
                    no_default=False):
    variables = get_vars_from_app(app_path, template_file)
    variables = list(variables) + ['sample_id', ]
    if no_default:
        app_default_var = AppDefaultVar(app_path)
        variables = app_default_var.diff(variables)

    for var in variables:
        if line_dict:
            if var not in line_dict.keys() and var != 'project_name':
                logger.warn('%s not in samples header.' % var)
                return False
        elif header_list:
            if var not in header_list and var != 'project_name':
                logger.warn('%s not in samples header.' % var)
                return False

    return True


def check_dir(path, skip=False, force=True):
    """Check whether path exists.

    :param path: directory path.
    :param skip: Boolean, Raise exception when skip is False and directory exists.
    :param force: Boolean, Force to make directory when directory doesn't exist?
    :return:
    """
    if not os.path.isdir(path):
        if force:
            os.makedirs(path)
        else:
            raise Exception("%s doesn't exist." % path)
    elif not skip:
        raise Exception("%s exists" % path)


class DictStruct:
    def __init__(self, **entries):
        self.__dict__.update(entries)


def parse_error(err):
    """Parse error string (formats) raised by (simple)json:

    '%s: line %d column %d (char %d)'
    '%s: line %d column %d - line %d column %d (char %d - %d)'
    """
    return re.match(r"""^
      (?P<msg>.+):\s+
      line\ (?P<lineno>\d+)\s+
      column\ (?P<colno>\d+)\s+
      (?:-\s+
        line\ (?P<endlineno>\d+)\s+
        column\ (?P<endcolno>\d+)\s+
      )?
      \(char\ (?P<pos>\d+)(?:\ -\ (?P<end>\d+))?\)$""", err, re.VERBOSE)


def check_json(json_file=None, string=''):
    try:
        if json_file:
            with open(json_file) as f:
                json.load(f)
        else:
            json.loads(string)
    except JSONDecodeError as error:
        if json_file:
            logger.error("Invalid JSON: %s" % json_file)
        else:
            logger.error("Invalid JSON")

        if json_file:
            with open(json_file) as f:
                string = f.read()

        string = StringIO(string)

        try:  # For Python2.7
            err_msg = error.message
            err_dict = parse_error(err_msg).groupdict()
        # Python3 AttributeError: 'JSONDecodeError' object has no attribute 'message'
        except Exception:  # For Python3
            err_msg = str(error)
            err_dict = parse_error(err_msg).groupdict()

        # cast int captures to int
        for k, v in err_dict.items():
            if v and v.isdigit():
                err_dict[k] = int(v)

        err = DictStruct(**err_dict)
        for ii, line in enumerate(string.readlines()):
            if ii == err.lineno - 1:
                logger.error("%s\n\n%s\n%s^-- %s\n" % (err_msg, line.replace("\n", ""),
                                                       " " * (err.colno - 1),
                                                       err.msg))

        sys.exit(JSON_NOT_VALID)


def copy_and_overwrite(from_path, to_path, is_file=False, ignore_errors=True, ask=False):
    if ask:
        answer = ''
        while answer.upper() not in ("YES", "NO", "Y", "N"):
            answer = input("Remove %s, Enter Yes/No: " % to_path)

            answer = answer.upper()
            if answer == "YES" or answer == "Y":
                ignore_errors = True
            elif answer == "NO" or answer == "N":
                ignore_errors = False
            else:
                print("Please enter Yes/No.")

    if ignore_errors:
        # TODO: rmtree is too dangerous
        if os.path.isfile(to_path):
            os.remove(to_path)

        if os.path.isdir(to_path):
            shutil.rmtree(to_path)

    try:
        if is_file and os.path.isfile(from_path):
            parent_dir = os.path.dirname(to_path)
            # Force to make directory when parent directory doesn't exist
            os.makedirs(parent_dir, exist_ok=True)
            shutil.copy2(from_path, to_path)
        elif os.path.isdir(from_path):
            shutil.copytree(from_path, to_path)
    except Exception as err:
        logger.warning('Copy %s to %s error: %s' %
                       (from_path, to_path, str(err)))


@click.group()
def version_cli():
    pass


@version_cli.command()
def version():
    """
    Show the version of app-utility.
    """
    print('Version %s' % VERSION)


@click.group()
def install_cli():
    pass


@install_cli.command()
@click.argument('choppy_app')
@click.option('--base-dir', '-b', help='The base directory for your apps.',
              default=DEFAULT_APP_ROOT_DIR, type=click.Path(exists=True))
@click.option('--username', '-u', help="The username of choppy app store.", required=True)
@click.option('--password', '-p', help="The password of choppy app store.", required=True)
@click.option('--endpoint', '-e', help="The endpoint of choppy app store.",
              default="http://choppy.3steps.cn")
@click.option('--force', '-f', help='Force to overwrite app. (default: False)', is_flag=True)
def install(choppy_app, base_dir, force, username, password, endpoint):
    """
    Install an app from a zip file or choppy store.
    """
    # Try Parse Choppy App Name with Zip Format
    app_name_lst = [os.path.splitext(os.path.basename(choppy_app))[0], ]
    # Try Parse Choppy App Name with Git Repo Format
    parsed_dict = parse_app_name(choppy_app)
    if parsed_dict:
        namespace = parsed_dict.get('namespace')
        app_name = parsed_dict.get('app_name')
        version = parsed_dict.get('version')
        app_name_lst.append('%s/%s-%s' % (namespace, app_name, version))

    app_root_dir = base_dir
    for app_name in app_name_lst:
        app_path = os.path.join(app_root_dir, app_name)
        # Overwrite If an app is installed.
        if os.path.exists(app_path):
            if force:
                shutil.rmtree(app_path, ignore_errors=True)
            else:
                print(
                    "%s is installed. If you want to reinstall, you can specify a --force flag." % app_name)
                sys.exit(APP_IS_INSTALLED)

    install_app(app_root_dir, choppy_app, endpoint, username, password)


@click.group()
def uninstall_cli():
    pass


@uninstall_cli.command()
@click.argument('app_name')
@click.option('--base-dir', '-b', default=DEFAULT_APP_ROOT_DIR,
              help='The base directory for your apps.',
              type=click.Path(exists=True))
def uninstall(app_name, base_dir):
    """
    Uninstall an app.
    """
    app_dir = os.path.join(base_dir, app_name)
    if not os.path.isdir(app_dir):
        raise NotFoundApp("The %s doesn't exist" % app_name)

    uninstall_app(base_dir, app_name)


@click.group()
def apps_cli():
    pass


@apps_cli.command()
@click.option('--base-dir', '-b', default=DEFAULT_APP_ROOT_DIR,
              help='The base directory for your apps.',
              type=click.Path(exists=True))
def apps(base_dir):
    """
    List all apps that is supported by choppy.
    """
    apps = listapps(base_dir)
    if len(apps) > 0:
        print(apps)
    else:
        print("No any installed app.")


@click.group()
def render_cli():
    pass


@render_cli.command()
@click.argument('app_name')
@click.argument('samples', type=click.Path(exists=True))
@click.option('--base-dir', '-b', default=DEFAULT_APP_ROOT_DIR,
              help='The base directory for your apps.',
              type=click.Path(exists=True))
@click.option('--work-dir', '-w', default=DEFAULT_PROJECT_ROOT_DIR,
              help='The working directory for your pipelines.',
              type=click.Path(exists=True))
@click.option('--project-name', '-p', help='Your project name. (default: None)', type=str, required=True)
@click.option('--force', '-f', help='Force to overwrite files. (default: False)', is_flag=True)
def render(app_name, samples, base_dir, work_dir, project_name, force):
    """
    Render as a pipeline based on the specified app template.
    """
    samples_file = click.format_filename(samples)
    app_dir = os.path.join(base_dir, app_name)
    project_path = os.path.join(work_dir, project_name)

    samples_data = parse_samples(samples)

    for sample in samples_data:
        if 'sample_id' not in sample.keys():
            raise Exception("Your samples file must contain sample_id column.")
        else:
            # 用户可通过samples文件覆写default文件中已定义的变量
            # 只有samples文件中缺少的变量才从default文件中取值
            app_default_var = AppDefaultVar(app_dir)
            all_default_value = app_default_var.show_default_value()

            for key in all_default_value.keys():
                if key not in sample.keys():
                    sample[key] = all_default_value.get(key)

            # make project_name/sample_id directory
            sample_path = os.path.join(project_path, sample.get('sample_id'))
            check_dir(sample_path, skip=force)

            sample['project_name'] = project_name

            # inputs
            inputs = render_app(app_dir, 'inputs', sample)
            check_json(string=inputs)  # Json Syntax Checker
            write(sample_path, 'inputs', inputs)
            inputs_path = os.path.join(sample_path, 'inputs')

            # workflow.wdl
            wdl = render_app(app_dir, 'workflow.wdl', sample)
            write(sample_path, 'workflow.wdl', wdl)
            wdl_path = os.path.join(sample_path, 'workflow.wdl')

            # defaults
            src_defaults_file = os.path.join(app_dir, 'defaults')
            dest_defaults_file = os.path.join(sample_path, 'defaults')
            copy_and_overwrite(src_defaults_file,
                               dest_defaults_file, is_file=True)

            src_dependencies = os.path.join(app_dir, 'tasks')
            dest_dependencies = os.path.join(sample_path, 'tasks')
            copy_and_overwrite(src_dependencies, dest_dependencies)

            # dependencies zip file
            zip_output = generate_dependencies_zip(src_dependencies)
            shutil.copy2(zip_output, sample_path)


main = click.CommandCollection(
    sources=[apps_cli, install_cli, uninstall_cli, render_cli, version_cli])

if __name__ == '__main__':
    main()
