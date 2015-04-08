"""dispatcher.py"""

import json

import jsonschema
import pkgutil
from inspect import getcallargs
from jsonrpcserver import rpc, request_log, response_log
from jsonrpcserver.exceptions import JsonRpcServerError, InvalidRequest, \
    MethodNotFound, InvalidParams, ServerError
from jsonrpcserver.status import HTTP_STATUS_CODES


_rpc_methods = {}
def add_rpc_method(name, func):
    """Add an rpc method to the list"""
    _rpc_methods[name] = func

def register_rpc_method(func):
    """Register an rpc method - used for the decorator."""
    add_rpc_method(func.__name__, func)

def convert_params_to_args_and_kwargs(params):
    """Takes the 'params' from the rpc request and converts it into args and
    kwargs to be passed through to the handling method.

    There are four possibilities for params:
        - No params at all.
        - args, eg. "params": [1, 2]
        - kwargs, eg. "params: {"foo": "bar"}
        - Both args and kwargs: [1, 2, {"foo": "bar"}]

    .. versionchanged:: 1.0.12
        No longer allows both args and kwargs, as per spec.

    :param params: The arguments for the JSON-RPC method.
    """

    args = kwargs = None

    # Params is a dict, ie. "params": {"foo": "bar"}
    if isinstance(params, dict):
        kwargs = params

    # Params is a list, ie. "params": ["foo", "bar"]
    elif isinstance(params, list):
        args = params

    return (args, kwargs)


def dispatch(request, more_info=False):
    """Call a method, based on the request.

    request: A dict containing the JSON request.

    ..versionchanged:: 1.0.12
        Sending "'id': null" will be treated as if no response is required.
    ..versionchanged:: 2.0.0
        Removed all flask code.
        No longer accepts a "handler".
    """
    #pylint:disable=too-many-branches

    request_log.info(json.dumps(request))

    try:

        # Validate
        try:
            jsonschema.validate(request, json.loads(pkgutil.get_data(__name__, \
                'request-schema.json').decode('utf-8')))
        except jsonschema.ValidationError as e:
            raise InvalidRequest(e.message)


        # Get the args and kwargs from request['params']
        (a, k) = convert_params_to_args_and_kwargs(request.get('params', None))


        # Dont allow magic methods to be called
        if request['method'].startswith('__') \
                and request['method'].endswith('__'):
            raise MethodNotFound(request['method'])


        # Get the method if available
        try:
            method = _rpc_methods[request['method']]
        except KeyError:
            raise MethodNotFound(request['method'])


        # Call the method
        if not a and not k:
            try:
                getcallargs(method)
            except TypeError as e:
                raise InvalidParams(str(e))
            result = method()

        if a and not k:
            try:
                getcallargs(method, *a)
            except TypeError as e:
                raise InvalidParams(str(e))
            result = method(*a)

        if not a and k:
            try:
                getcallargs(method, **k)
            except TypeError as e:
                raise InvalidParams(str(e))
            result = method(**k)

#        if a and k: # should never happen
#            raise InvalidParams('Using both positional and keyword \
#            arguments is not supported by the JSON-RPC protocol')

        # Return a response
        request_id = request.get('id', None)
        if request_id is not None:
            result, status = rpc.result(request_id, result), 200
        else:
            result, status = (None, 204)

    # Catch JsonRpcServerErrors raised (invalid request etc)
    except JsonRpcServerError as e:
        e.request_id = request.get('id', None)
        result, status = (json.loads(str(e)), e.http_status_code)
        if not more_info:
            result['error'].pop('data')

    # Catch all other exceptions
    except Exception as e:
        e.request_id = request.get('id', None)
        result, status = (json.loads(str(ServerError('Server error', str(e)))), 500)
        if not more_info:
            result['error'].pop('data')

    response_log.info(str(result), extra={
        'http_code': status,
        'http_reason': HTTP_STATUS_CODES[status]
    })

    return (result, status)
