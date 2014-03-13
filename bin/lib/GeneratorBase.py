import os
import os.path

from abc import ABCMeta, abstractmethod

from myrpcgen.Constants import VERSION, ENCODING
from myrpcgen.InternalException import InternalException

class StructFieldAccess:
    """What kind of getter/setter will be generated?"""

    (UNDERSCORE,
     CAPITAL,
     DIRECT) = range(3)

class GeneratorBase(metaclass = ABCMeta):
    """Base class for generator implementation classes."""

    _generators = {}

    def __init__(self, namespace, tm, methods, indent, sfa, outdir):
        self._namespace = namespace
        self._tm = tm
        self._methods = methods
        self._indent = indent
        self._sfa = sfa
        self._outdir = outdir

        self._gtm = GeneratorTypeManager()
        self._filename = None
        self._content = None

    def create_outdir(self):
        try:
            os.mkdir(self._outdir)
        except FileExistsError:
            pass
        except OSError as e:
            raise GeneratorException(e)

    @abstractmethod
    def gen_types(self):
        pass

    @abstractmethod
    def gen_client(self):
        pass

    @abstractmethod
    def gen_processor(self):
        pass

    @staticmethod
    @abstractmethod
    def validate_ns(ns):
        """Validate language specific namespace.

        If namespace is invalid, ValueError is thrown.
        """

        pass

    @abstractmethod
    def _get_comment_prefix(self):
        pass

    @abstractmethod
    def _get_var_prefix(self):
        pass

    def _open(self, filename):
        self._filename = os.path.join(self._outdir, filename)
        self._content = ""

    def _whdr(self):
        comment_prefix = self._get_comment_prefix()

        self._wl("{} THIS FILE IS AUTOMATICALLY GENERATED BY {}. DO NOT EDIT.".format(comment_prefix, VERSION))
        self._wl("")

    def _wl(self, line):
        self._ws("{}\n".format(line))

    def _ws(self, s):
        self._content += s

    def _close(self):
        indent = self._indent * " "
        content = self._content.replace("\t", indent)

        if content.endswith("\n\n"):
            content = content[:-1]

        try:
            f = open(self._filename, mode = "xt", encoding = ENCODING)
            f.write(content)
            f.close()
        except OSError as e:
            raise GeneratorException(e)

    def _register_dtype_kinds(self, dtype_kinds):
        for (dtype_kind, info) in dtype_kinds.items():
            self._gtm.register_dtype_kind(dtype_kind, info)

    def _sort_by_name(self, objs):
        objs_sorted = sorted(objs, key = lambda obj: obj.get_name())

        return objs_sorted

    def _sfa_check_start(self, dtype_name):
        self._sfa_dtype_name = dtype_name
        self._sfa_names = set()

    def _sfa_check_name(self, name):
        # Check if a given setter/getter name is unique in a struct.

        if name in self._sfa_names:
            raise GeneratorException("sfa conflict for method {} in {}".format(name, self._sfa_dtype_name))

        self._sfa_names.add(name)

    def _get_struct_field_var_name(self, name, sfa):
        # Calculate an expression which can be used to access a given
        # field from inside the struct.

        prefix = "{}".format(self._get_var_prefix())

        if (sfa == StructFieldAccess.UNDERSCORE or
            sfa == StructFieldAccess.CAPITAL):
            var_name = "{}._{}".format(prefix, name)
        elif sfa == StructFieldAccess.DIRECT:
            var_name = "{}.{}".format(prefix, name)
        else:
            raise InternalException("sfa {} is unknown".format(sfa))

        return var_name

    def _get_struct_field_getter_name(self, name, sfa):
        # Calculate getter method name, return None if not needed.

        if sfa == StructFieldAccess.UNDERSCORE:
            getter_name = "get_{}".format(name)
        elif sfa == StructFieldAccess.CAPITAL:
            firstchar = name[0].upper()
            rest = name[1:]
            getter_name = "get{}{}".format(firstchar, rest)
        elif sfa == StructFieldAccess.DIRECT:
            getter_name = None
        else:
            raise InternalException("sfa {} is unknown".format(sfa))

        return getter_name

    def _get_struct_field_setter_name(self, name, sfa):
        # Calculate setter method name, return None if not needed.

        if sfa == StructFieldAccess.UNDERSCORE:
            setter_name = "set_{}".format(name)
        elif sfa == StructFieldAccess.CAPITAL:
            firstchar = name[0].upper()
            rest = name[1:]
            setter_name = "set{}{}".format(firstchar, rest)
        elif sfa == StructFieldAccess.DIRECT:
            setter_name = None
        else:
            raise InternalException("sfa {} is unknown".format(sfa))

        return setter_name

    def _get_struct_field_getter_invoke(self, obj, name, v, sfa):
        # Invoke getter on a given object and field name.

        if (sfa == StructFieldAccess.UNDERSCORE or
            sfa == StructFieldAccess.CAPITAL):
            getter_name = self._get_struct_field_getter_name(name, sfa)
            getter_invoke = "{} = {}.{}()".format(v, obj, getter_name)
        elif sfa == StructFieldAccess.DIRECT:
            getter_invoke = "{} = {}.{}".format(v, obj, name)
        else:
            raise InternalException("sfa {} is unknown".format(sfa))

        return getter_invoke

    def _get_struct_field_setter_invoke(self, obj, name, v, sfa):
        # Invoke setter on a given object and field name.

        if (sfa == StructFieldAccess.UNDERSCORE or
            sfa == StructFieldAccess.CAPITAL):
            setter_name = self._get_struct_field_setter_name(name, sfa)
            setter_invoke = "{}.{}({})".format(obj, setter_name, v)
        elif sfa == StructFieldAccess.DIRECT:
            setter_invoke = "{}.{} = {}".format(obj, name, v)
        else:
            raise InternalException("sfa {} is unknown".format(sfa))

        return setter_invoke

    @staticmethod
    def register_gen(gen_name, gen_class):
        if gen_name in GeneratorBase._generators:
            raise InternalException("Generator {} is already registered".format(gen_name))

        GeneratorBase._generators[gen_name] = gen_class

    @staticmethod
    def list_gen():
        gen_names = sorted(GeneratorBase._generators.keys())

        return gen_names

    @staticmethod
    def lookup_gen(gen_name):
        """Lookup the specified generator.

        If generator is not exist, KeyError is thrown.
        """

        gen_class = GeneratorBase._generators[gen_name]

        return gen_class

class GeneratorTypeManager:
    """Generator type manager."""

    def __init__(self):
        self._dtype_kinds = {}

    def register_dtype_kind(self, dtype_kind, info):
        if dtype_kind in self._dtype_kinds:
            raise InternalException("dtype_kind {} is already registered".format(dtype_kind))

        self._dtype_kinds[dtype_kind] = info

    def get_codec_dtype(self, dtype):
        info = self._lookup_dtype(dtype)
        codec_dtype = info[0]

        return codec_dtype

    def gen_dtype(self, dtype):
        info = self._lookup_dtype(dtype)
        s = info[1](dtype)

        return s

    def read_dtype(self, dtype, v):
        info = self._lookup_dtype(dtype)
        s = info[2](dtype, v)

        return s

    def write_dtype(self, dtype, v):
        info = self._lookup_dtype(dtype)
        s = info[3](dtype, v)

        return s

    def _lookup_dtype(self, dtype):
        dtype_kind = dtype.get_dtype_kind()
        info = self._dtype_kinds[dtype_kind]

        return info

class StringBuilder:
    """String builder class."""

    def __init__(self):
        self._s = ""

    def get_string(self):
        return self._s

    def wl(self, line):
        self._s += "{}\n".format(line)

    def we(self):
        self.wl("")

    def wlsindent(self, indent, lines):
        l = lines.rstrip("\n").split("\n")

        for s in l:
            self.wl("{}{}".format(indent, s))

class GeneratorException(Exception):
    """Generator exception class."""

    def __init__(self, msg):
        super().__init__()

        self._msg = str(msg)

    def __str__(self):
        return self._msg
