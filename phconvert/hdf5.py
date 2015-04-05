#
# phconvert - Convert files to Photon-HDF5 format
#
# Copyright (C) 2014-2015 Antonino Ingargiola <tritemio@gmail.com>
#
"""
This module defines the function :func:`photon_hdf5` to save data from a
dictionary to **Photon-HDF5** format. The keys of the dictionary must be
valid field names in the Photon-HDF5 format.

It also provides functions to save free-form dict to HDF5
(:func:`dict_to_group`) and read a HDF5 group into a dict
(:func:`dict_from_group`).

Finally there are utility functions to easily print HDF5 nodes and attributes.
"""

from __future__ import print_function, absolute_import, division

import os
import time
import re
import tables

from .metadata import official_fields_descr
from ._version import get_versions


__version__ = get_versions()['version']


def _analyze_path(name, prefix_list):
    """
    From a name (string) and a prefix_list (list of strings)

    Returns:
        - (string) the meta_path, that is a string with the full HDF5 path
          with possible trailing digits removed from "/photon_dataNN"
        - (bool) whether `name` is a photon_data array, i.e. a direct child of
          photon_data and not a specs group.
        - (bool) whether `name` is a user-defined field.

    """
    assert name[0] != '/' and name[-1] != '/'
    full_path = '/' + name
    if prefix_list is not None and len(prefix_list) > 0:
        prefix = '/'.join(prefix_list)
        assert prefix[0] != '/' and prefix[-1] != '/'
        full_path = '/' + prefix + full_path
    chunks = full_path.split('/')
    assert len(chunks) >= 2
    assert name == chunks[-1]

    #group_path = '/'.join(chunks[:-1]) + '/'
    is_user = 'user' in chunks

    meta_path = full_path
    is_phdata = False
    if full_path.startswith('/photon_data'):
        if len(chunks) == 3 and not name.endswith('_specs'):
            is_phdata = True
        # Remove eventual digits after /photon_data
        pattern = '/photon_data[0-9]*(.*)'
        meta_path = '/photon_data' + \
                    re.match(pattern, full_path).group(1)

    return meta_path, is_phdata, is_user


def _h5_write_array(group, name, obj, descr=None, chunked=False):
    h5file = group._v_file
    if chunked:
        save = h5file.create_carray
    else:
        save = h5file.create_array
    if isinstance(obj, str):
        obj = obj.encode()
    save(group, name, obj=obj, title=descr)


def _save_photon_hdf5_dict(group, data_dict, fields_descr, prefix_list=None,
                           debug=False):
    """
    Assumptions:
        data_dict is a hierarchical dict whose values are either arrays or
        sub-dictionaries representing a sub-group.

        fields_descr merges official and user-defined field descriptions
        where the key is always the normalized full path (meta path).
        The meta path is the full path where the string "/photon_dataNN"
        is replaced by "/photon_data".
    """
    if debug:
        print('Call: group %s, prefix_list %s ' % (group._v_name, prefix_list))
    h5file = group._v_file
    for name, value in data_dict.items():
        descr_key, is_phdata, is_user = _analyze_path(name, prefix_list)
        if debug:
            print('Item: %s    Descr key: %s' % (name, descr_key))
        # Allow missing description in user fields
        description = fields_descr.get(descr_key, '')
        if not is_user:
            #assert description is not None,
            #       'Name "%s" is not valid.' % descr_key
            if description is '':
                print('WARNING: missing description for "%s"' % descr_key)

        if isinstance(value, dict):
            # Current key is a group, create it and walk through its content
            subgroup = h5file.create_group(group, name, title=description)

            new_prefix_list = [] if prefix_list is None else list(prefix_list)
            new_prefix_list.append(name)
            _save_photon_hdf5_dict(subgroup, value, fields_descr,
                                   new_prefix_list)
        else:
            if debug:
                print(' - Saving %s, value: "%s"' % (name, value))
            _h5_write_array(group, name, obj=value, descr=description,
                            chunked=is_phdata)
    if debug:
        print('End Call: group %s, prefix_list %s ' % (group._v_name,
                                                       prefix_list))


def save_photon_hdf5(data_dict, compression=dict(complevel=6, complib='zlib'),
                     h5_fname=None,
                     user_descr=None,
                     debug=False):
    """
    Saves the dict `d` in the Photon-HDF5 format.

    As a side effect `d` is modified by adding the key 'data_file' that
    contains a reference to the pytables file.

    Arguments:
        data_dict (dict): the dictionary containing the photon data.
            The keys must strings matching valid Photon-HDF5 paths.
            The values must be scalars, arrays or strings.
        compression (dict): a dictionary containing the compression type
            and level. Passed to pytables `tables.Filters()`.
        h5_fname (string or None): if not None, contains the file name
            to be used for the HDF5 file. If None, the file name is
            generated from d['filenamename'], by replacing the original
            extension with '.hdf5'.
        user_descr (dict or None): dictionary of field descriptions for
            user-defined fields. The keys must be strings representing
            the full HDF5 path of each field.

    For description and specs of the Photon-HDF5 format see:
    http://photon-hdf5.readthedocs.org/
    """
    comp_filter = tables.Filters(**compression)

    if h5_fname is None:
        basename, extension = os.path.splitext(data_dict.pop('filename'))
        if compression['complib'] == 'blosc':
            basename += '_blosc'
        h5_fname = basename + '.hdf5'

    if os.path.isfile(h5_fname):
        basename, extension = os.path.splitext(h5_fname)
        h5_fname = basename + '_new_copy.hdf5'

    print('Saving: %s' % h5_fname)
    title = official_fields_descr['/']
    data_file = tables.open_file(h5_fname, mode="w", title=title,
                                 filters=comp_filter)
    # Saving a file reference is useful in case of error
    backup = data_dict
    data_dict = data_dict.copy()
    backup.update(data_file=data_file)

    ## Add provenance metadata
    if 'provenance' in data_dict:
        provenance = data_dict['provenance']
        orig_fname = None
        if os.path.isfile(provenance['filename']):
            orig_fname = provenance['filename']
        elif os.path.isfile(provenance['filename_full']):
            orig_fname = provenance['filename_full']
        else:
            print("WARNING: Could not locate original file '%s'" % \
                  provenance['filename'])
        if orig_fname is not None:
            provenance.update(get_file_metadata(orig_fname))

    ## Add identity metadata
    full_h5filename = os.path.abspath(h5_fname)
    h5filename = os.path.basename(full_h5filename)
    creation_time = time.strftime("%Y-%m-%d %H:%M:%S")
    identity = dict(filename=h5filename,
                    filename_full=full_h5filename,
                    creation_time=creation_time,
                    software='phconvert',
                    software_version=__version__,
                    format_name='Photon-HDF5',
                    format_version='0.3',
                    format_url='http://photon-hdf5.readthedocs.org/')
    data_dict['identity'] = identity

    ## Save everything to disk
    fields_descr = official_fields_descr.copy()
    if user_descr is not None:
        fields_descr.update(user_descr)
    _save_photon_hdf5_dict(data_file.root, data_dict,
                           fields_descr=fields_descr, debug=debug)
    data_file.flush()


def get_file_metadata(fname):
    """Return a dict with file metadata.
    """
    assert os.path.isfile(fname)

    full_filename = os.path.abspath(fname)
    filename = os.path.basename(full_filename)

    # Creation and modification time (but not exactly on *NIX)
    # see https://docs.python.org/2/library/os.path.html#os.path.getctime)
    ctime = time.localtime(os.path.getctime(full_filename))
    mtime = time.localtime(os.path.getmtime(full_filename))

    ctime_str = time.strftime("%Y-%m-%d %H:%M:%S", ctime)
    mtime_str = time.strftime("%Y-%m-%d %H:%M:%S", mtime)

    metadata = dict(filename=filename, filename_full=full_filename,
                    creation_time=ctime_str, modification_time=mtime_str)
    return metadata


def dict_from_group(group):
    """Return a dict with the content of a PyTables `group`."""
    out = {}
    for node in group:
        if isinstance(node, tables.Group):
            value = dict_from_group(node)
        else:
            value = node.read()
        out[node._v_name] = value
    return out

def dict_to_group(group, dictionary):
    """Save `dictionary` into HDF5 format in `group`.
    """
    h5file = group._v_file
    for key, value in dictionary.items():
        if isinstance(value, dict):
            subgroup = h5file.create_group(group, key)
            dict_to_group(subgroup, value)
        else:
            h5file.create_array(group, name=key, obj=value)
    h5file.flush()

def load_photon_hdf5(filename, strict=True):
    assert os.path.isfile(filename)
    h5file = tables.open_file(filename)
    assert_valid_photon_hdf5(h5file.root, strict=strict)
    return h5file.root


class Invalid_PhotonHDF5(Exception):
    """Error raised when a file is not a valid Photon-HDF5 file.
    """
    pass

def _raise_invalid_file(msg, strict=True):
    """Raise Invalid_PhotonHDF5 if strict is True, print a warning otherwise.
    """
    if strict:
        raise Invalid_PhotonHDF5(msg)
    else:
        print('Photon-HDF5 WARNING: %s' % msg)

def _check_has_field(name, group, strict=True):
    msg = 'Missing "%s" in "%s".'
    if name not in group:
        _raise_invalid_file(msg % (name, group._v_pathname))

def _check_path(path, strict=True):
    if '/user' in path:
        return

    if path.startswith('/photon_data'):
        # Remove eventual digits after /photon_data
        pattern = '/photon_data[0-9]*(.*)'
        path = '/photon_data' + re.match(pattern, path).group(1)

    if path not in official_fields_descr:
        msg = ('Unknown field "%s". '
               'Custom fields must be inside a "user" group.' % path)
        if strict:
            raise Invalid_PhotonHDF5(msg)
        else:
            print('Photon-HDF5 WARNING: %s' % msg)

def _check_valid_names(data, strict=True):
    already_verified = []
    for group in data._f_walk_groups():
        path = group._v_pathname
        _check_path(path, strict=strict)
        already_verified.append(path)
        for node in group._f_iter_nodes():
            path = node._v_pathname
            if path not in already_verified:
                _check_path(path, strict=strict)
                already_verified.append(path)


def assert_valid_photon_hdf5(data, strict=True):
    """
    Validate the structure of a Photon-HDF5 file.

    Raise an error when missing photon_data group, timestamps array and
    timestamps_unit.

    When `strict` is True, raise an error if
    """
    _check_valid_names(data, strict=strict)
    _check_has_field('acquisition_time', data, strict=strict)
    _check_has_field('comment', data, strict=strict)

    if 'photon_data' in data:
        ph_data_m = [data.photon_data]
    elif 'photon_data0' in data:
        ph_data_m = [k for k in data._v_groups.keys()
                     if k.startswith('photon_data')]
        ph_data_m.sort()
    else:
        msg = 'Invalid Photon-HDF5: missing "photon_data" group.'
        raise Invalid_PhotonHDF5(msg)

    for ph_data in ph_data_m:
        _check_photon_data(ph_data, strict=strict)

    if 'setup' in data:
        _check_setup(data.setup, strict=strict)
    else:
        _raise_invalid_file('Invalid Photon-HDF5: Missing /setup group.',
                            strict)

def _check_setup(setup, strict=True):
    mantatory_fields = ['num_pixels', 'num_spots', 'num_spectral_ch',
                        'num_polarization_ch', 'num_split_ch',
                        'modulated_excitation', 'lifetime']
    for name in mantatory_fields:
        if name not in setup:
            _raise_invalid_file('Missing "/setup/%s".' % name, strict)

def _check_photon_data(ph_data, strict=True):

    def _assert_has_field(name, group):
        msg = 'Missing "%s" in "%s".'
        if name not in group:
            raise Invalid_PhotonHDF5(msg % (name, group._v_pathname))

    _assert_has_field('timestamps', ph_data)
    _assert_has_field('timestamps_specs', ph_data)
    _assert_has_field('timestamps_unit', ph_data.timestamps_specs)

    spectral_meas_types = ['smFRET',
                           'smFRET-usALEX', 'smFRET-usALEX-3c',
                           'smFRET-nsALEX']
    if 'measurement_specs' not in ph_data:
        _raise_invalid_file('Missing "measurement_specs".', strict)
        return

    measurement_specs = ph_data.measurement_specs
    if 'measurement_type' not in measurement_specs:
        _raise_invalid_file('Missing "measurement_type"', strict)
        return

    measurement_type = measurement_specs.measurement_type.read()
    if measurement_type not in spectral_meas_types:
        raise Invalid_PhotonHDF5('Unkwnown measurement type "%s"' % \
                                 measurement_type)

    # At this point we have a valid measurement_type
    # Any missing field will raise an error (regardless of `strict`).
    def _assert_has_field_mtype(name, group):
        msg = 'Missing "%s" in "%s".\nThis field is mandatory for "%s" data.'
        if name not in group:
            raise Invalid_PhotonHDF5(msg % (name, group._v_pathname,
                                            measurement_type))

    detectors_specs = measurement_specs.detectors_specs
    _assert_has_field_mtype('spectral_ch1', detectors_specs)
    _assert_has_field_mtype('spectral_ch2', detectors_specs)

    if measurement_type in ['smFRET-usALEX', 'smFRET-usALEX-3c']:
        _assert_has_field_mtype('alex_period', measurement_specs)

    if measurement_type == 'smFRET-nsALEX':
        _assert_has_field_mtype('laser_pulse_rate', measurement_specs)
        _assert_has_field_mtype('nantotimes', ph_data)
        _assert_has_field_mtype('nantotimes_specs', ph_data)
        for name in ['tcspc_unit', 'tcspc_range', 'tcspc_num_bins',
                     'time_reversed']:
             _assert_has_field_mtype(name, ph_data.nantotimes_specs)


def print_attrs(data_file, node_name='/', which='user'):
    """Print the HDF5 attributes for `node_name`.

    Parameters:
        data_file (pytables HDF5 file object): the data file to print
        node_name (string): name of the path inside the file to be printed.
            Can be either a group or a leaf-node. Default: '/', the root node.
        which (string): Valid values are 'user' for user-defined attributes,
            'sys' for pytables-specific attributes and 'all' to print both
            groups of attributes. Default 'user'.
    """
    node = data_file.get_node(node_name)
    print('List of attributes for:\n  %s\n' % node)
    for attr in node._v_attrs._f_list(which):
        print('\t%s' % attr)
        print('\t    %s' % repr(node._v_attrs[attr]))


def print_children(data_file, group='/'):
    """Print all the sub-groups in `group` and leaf-nodes children of `group`.

    Parameters:
        data_file (pytables HDF5 file object): the data file to print
        group (string): path name of the group to be printed.
            Default: '/', the root node.
    """
    base = data_file.get_node(group)
    print('Groups in:\n  %s\n' % base)

    for node in base._f_walk_groups():
        if node is not base:
            print('    %s' % node)

    print('\nLeaf-nodes in %s:' % group)
    for node in base._v_leaves.itervalues():
        info = node.shape
        if len(info) == 0:
            info = node.read()
        print('\t%s, %s' % (node.name, info))
        if len(node.title) > 0:
            print('\t    %s' % node.title)

del print_function
