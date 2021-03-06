import re

from myrpcgen.Constants import MYRPC_PREFIX, U_MYRPC_PREFIX, IDENTIFIER_RE, RESULT_FIELD_NAME
from myrpcgen.GeneratorBase import StructFieldAccess, GeneratorBase, StringBuilder, GeneratorException
from myrpcgen.TypeManager import DataTypeKind
from myrpcgen.InternalException import InternalException

class Target:
    """Specifies JavaScript target."""

    (BROWSER,
     NODE) = range(2)

_TARGET = "browser" # Default, must be in _TARGET_CHOICES.
_TARGET_CHOICES = {"browser": Target.BROWSER,
                   "node":    Target.NODE}

_TYPES_MODULE = "Types"
_TYPES_FILENAME = "{}.js".format(_TYPES_MODULE)
_CLIENT_FILENAME = "Client.js"
_PROCESSOR_FILENAME = "Processor.js"
_ONCONTINUE = "{}{}".format(MYRPC_PREFIX, "oncontinue")
_CONTINUE = "{}{}".format(MYRPC_PREFIX, "continue")
_ARGS_RESULT_SERI_SFA = StructFieldAccess.UNDERSCORE
_STRUCT_READ = "{}read".format(MYRPC_PREFIX)
_STRUCT_WRITE = "{}write".format(MYRPC_PREFIX)
_STRUCT_VALIDATE = "{}validate".format(U_MYRPC_PREFIX)
_NODE_NS = "{}gen".format(MYRPC_PREFIX)
_NS_SEPARATOR = "."

class JSGenerator(GeneratorBase):
    """Generator for JavaScript."""

    def __init__(self, namespace, tm, methods, indent, sfa, outdir, overwrite, args):
        super().__init__(namespace, tm, methods, indent, sfa, outdir, overwrite, args)

    def setup_gen(self):
        self._target = _TARGET_CHOICES[self._args.js_target]
        if self._target == Target.BROWSER:
            self._validate_ns()
        elif self._target == Target.NODE:
            # Node target uses _NODE_NS as namespace.

            self._namespace = _NODE_NS
        else:
            raise InternalException("target {} is unknown".format(self._target))

        self._dtype_classp = "{}.Types".format(self._namespace)
        self._enum_read_funcp = "{}.{}enum_read".format(self._dtype_classp, MYRPC_PREFIX)
        self._enum_write_funcp = "{}.{}enum_write".format(self._dtype_classp, MYRPC_PREFIX)
        self._enum_validate_funcp = "{}.{}enum_validate".format(self._dtype_classp, MYRPC_PREFIX)
        self._list_read_funcp = "{}.{}list_read".format(self._dtype_classp, MYRPC_PREFIX)
        self._list_write_funcp = "{}.{}list_write".format(self._dtype_classp, MYRPC_PREFIX)
        self._args_seri_classp = "{}.{}args_seri".format(self._dtype_classp, MYRPC_PREFIX)
        self._result_seri_classp = "{}.{}result_seri".format(self._dtype_classp, MYRPC_PREFIX)
        self._codec_dtype_classp = "myrpc.codec.DataType"
        self._client_classn = "{}.Client".format(self._namespace)
        self._processor_classn = "{}.Processor".format(self._namespace)
        self._exc_handler_funcp = "{}exc_handler".format(U_MYRPC_PREFIX)

        self._setup_dtype_kinds()

    def gen_types(self):
        self._open(_TYPES_FILENAME)

        # Do target specific namespace creation.

        if self._target == Target.BROWSER:
            # Create JavaScript namespace. Types.js should be included first,
            # before any other generated files.

            sb = StringBuilder()

            compl = self._namespace.split(_NS_SEPARATOR)

            for i in range(len(compl)):
                current_namespace = compl[i]
                parent_namespace = "window" if i == 0 else _NS_SEPARATOR.join(compl[:i])

                sb.wl("if (!(\"{0}\" in {1})) {1}{2}{0} = {{}};".format(current_namespace, parent_namespace, _NS_SEPARATOR))

            sb.we()

            self._ws(sb.get_string())
        elif self._target == Target.NODE:
            self._wheader_node(("codec/CodecBase",), True)
        else:
            raise InternalException("target {} is unknown".format(self._target))

        sb = StringBuilder()

        sb.wl("{} = {{}};".format(self._dtype_classp))
        sb.we()

        self._ws(sb.get_string())

        self._gen_types()
        self._gen_args_result_seri()

        if self._target == Target.NODE:
            self._wfooter_node()

        self._close()

    def gen_client(self):
        self._open(_CLIENT_FILENAME)

        if self._target == Target.NODE:
            self._wheader_node(("util/ClientSubr",), False)

        self._gen_client()
        self._gen_exc_handler()

        if self._target == Target.NODE:
            self._wfooter_node()

        self._close()

    def gen_processor(self):
        self._open(_PROCESSOR_FILENAME)

        if self._target == Target.NODE:
            self._wheader_node(("util/ProcessorSubr",), False)

        # We don't support abstract interface generation for JavaScript,
        # because the language itself doesn't support it.

        self._gen_processor()

        if self._target == Target.NODE:
            self._wfooter_node()

        self._close()

    @staticmethod
    def setup_argparse(parser):
        group = parser.add_argument_group("js specific arguments")
        group.add_argument("--js_target", dest = "js_target",
                           choices = _TARGET_CHOICES,
                           default = _TARGET,
                           help = "code generation target (default: {})".format(_TARGET))

    def _validate_ns_impl(self):
        if self._namespace == None:
            raise ValueError()

        for comp in self._namespace.split(_NS_SEPARATOR):
            if not re.match(IDENTIFIER_RE, comp):
                raise ValueError()

    def _get_comment_prefix(self):
        return "//"

    def _get_var_prefix(self):
        return "this"

    def _gen_types(self):
        dtypes = self._sort_by_name(self._tm.list_dtype())

        for dtype in dtypes:
            s = self._gtm.gen_dtype(dtype)
            self._ws(s)

    def _gen_args_result_seri(self):
        methods = self._sort_by_name(self._methods)

        for method in methods:
            name = method.get_name()
            in_struct = method.get_in_struct()
            out_struct = method.get_out_struct()
            args_seri_classn = self._get_args_seri_classn(name)
            result_seri_classn = self._get_result_seri_classn(name)

            # Use fixed sfa during method args/result seri generation, because
            # setter/getter naming can have dependencies in client/processor subrs.

            s = self._dtype_kind_struct_gen(in_struct, args_seri_classn, _ARGS_RESULT_SERI_SFA)
            self._ws(s)

            s = self._dtype_kind_struct_gen(out_struct, result_seri_classn, _ARGS_RESULT_SERI_SFA)
            self._ws(s)

    def _gen_client(self):
        sb = StringBuilder()

        sb.wl("{} = function(tr, codec)".format(self._client_classn))
        sb.wl("{")
        sb.wl("\tthis._client = new myrpc.util.ClientSubr(tr, codec);")
        sb.wl("};")
        sb.we()

        methods = self._sort_by_name(self._methods)

        for method in methods:
            name = method.get_name()
            in_struct = method.get_in_struct()
            args_seri_classn = self._get_args_seri_classn(name)
            result_seri_classn = self._get_result_seri_classn(name)
            exc_handler_funcn = self._get_exc_handler_funcn(name)

            in_field_names = [field.get_name() for field in in_struct.get_fields()]
            args = ["arg_{}".format(in_field_name) for in_field_name in in_field_names]

            args_oncontinue = args.copy()
            args_oncontinue.append(_ONCONTINUE)
            args_oncontinuef = ", ".join(args_oncontinue)

            sb.wl("{}.prototype.{} = function({})".format(self._client_classn, name, args_oncontinuef))
            sb.wl("{")
            sb.wl("\tvar args_seri;")
            sb.wl("\tvar result_seri;")
            sb.wl("\tvar exc_handler;")
            sb.we()

            sb.wl("\targs_seri = new {}();".format(args_seri_classn))

            for i in range(len(in_field_names)):
                in_field_name = in_field_names[i]
                arg = args[i]
                setter_invoke = self._get_struct_field_setter_invoke("args_seri", in_field_name, arg, _ARGS_RESULT_SERI_SFA)

                sb.wl("\t{};".format(setter_invoke))

            sb.we()

            sb.wl("\tresult_seri = new {}();".format(result_seri_classn))
            sb.we()

            sb.wl("\texc_handler = myrpc.common.proxy(this.{}, this);".format(exc_handler_funcn))
            sb.we()

            sb.wl("\tthis._client.call(\"{}\", args_seri, result_seri, exc_handler, {}, this);".format(name, _ONCONTINUE))

            sb.wl("};")
            sb.we()

        sb.wl("{}.prototype.{} = function()".format(self._client_classn, _CONTINUE))
        sb.wl("{")
        sb.wl("\tvar r = this._client.call_continue();")
        sb.we()
        sb.wl("\treturn r;")
        sb.wl("};")
        sb.we()

        self._ws(sb.get_string())

    def _gen_exc_handler(self):
        sb = StringBuilder()

        methods = self._sort_by_name(self._methods)

        for method in methods:
            name = method.get_name()
            excs = method.get_excs()
            funcn = self._get_exc_handler_funcn(name)

            sb.wl("{}.prototype.{} = function(codec, name)".format(self._client_classn, funcn))
            sb.wl("{")
            sb.wl("\tvar excmap = {")

            lasti = len(excs) - 1

            for (i, exc) in enumerate(excs):
                exc_name = exc.get_name()
                exc_classn = self._get_dtype_classn(exc_name)

                # Use MYRPC_PREFIX as prefix before exception names. It is
                # needed because JavaScript objects contain built-in members
                # (e.g. toString).

                sb.wl("\t\t\"{}{}\": {}{}".format(MYRPC_PREFIX, exc_name, exc_classn, "," if i < lasti else ""))

            sb.wl("\t};")
            sb.wl("\tvar exc_name = \"{}\" + name;".format(MYRPC_PREFIX))
            sb.wl("\tvar exc_class;")
            sb.wl("\tvar exc;")
            sb.we()

            sb.wl("\tif (!(exc_name in excmap))")
            sb.wl("\t\tthrow new myrpc.common.MessageHeaderException(\"Unknown exception name \" + name);")
            sb.we()

            sb.wl("\texc_class = excmap[exc_name];")
            sb.wl("\texc = new exc_class();")
            sb.wl("\texc.{}(codec);".format(_STRUCT_READ))
            sb.we()

            sb.wl("\treturn exc;")
            sb.wl("};")
            sb.we()

        self._ws(sb.get_string())

    def _gen_processor(self):
        sb = StringBuilder()

        sb.wl("{} = function(impl)".format(self._processor_classn))
        sb.wl("{")
        sb.wl("\tvar methodmap = {")

        methods = self._sort_by_name(self._methods)

        lasti = len(methods) - 1

        for (i, method) in enumerate(methods):
            name = method.get_name()
            args_seri_classn = self._get_args_seri_classn(name)

            # Use MYRPC_PREFIX as prefix before exception names. It is
            # needed because JavaScript objects contain built-in members
            # (e.g. toString).

            sb.wl("\t\t\"{0}{1}\": [{2}, myrpc.common.proxy(this._handle_{1}, this)]{3}".format(MYRPC_PREFIX, name, args_seri_classn, "," if i < lasti else ""))

        sb.wl("\t};")
        sb.we()

        sb.wl("\tthis._impl = impl;")
        sb.wl("\tthis._proc = new myrpc.util.ProcessorSubr(methodmap);")
        sb.wl("};")
        sb.we()

        sb.wl("{}.prototype.process_one = function(tr, codec)".format(self._processor_classn))
        sb.wl("{")
        sb.wl("\tvar finished = this._proc.process_one(tr, codec);")
        sb.we()
        sb.wl("\treturn finished;");
        sb.wl("};")
        sb.we()

        sb.wl("{}.prototype.call_continue = function(func, user_data)".format(self._processor_classn))
        sb.wl("{")
        sb.wl("\tvar finished = this._proc.call_continue(func, user_data);")
        sb.we()
        sb.wl("\treturn finished;");
        sb.wl("};")
        sb.we()

        for method in methods:
            name = method.get_name()
            in_struct = method.get_in_struct()
            excs = method.get_excs()
            has_result = method.has_result()
            has_excs = len(excs) > 0
            result_seri_classn = self._get_result_seri_classn(name)

            sb.wl("{}.prototype._handle_{} = function(args_seri, func, user_data)".format(self._processor_classn, name))
            sb.wl("{")

            in_field_names = [field.get_name() for field in in_struct.get_fields()]
            args = ["arg_{}".format(in_field_name) for in_field_name in in_field_names]
            argsf = ", ".join(args)

            for arg in args:
                sb.wl("\tvar {};".format(arg))

            sb.wl("\tvar exc_name = null;")
            sb.wl("\tvar exc;")
            sb.wl("\tvar r = null;")
            sb.wl("\tvar hr;")
            sb.wl("\tvar result_seri;")
            sb.we()

            if len(in_field_names) > 0:
                sb.wl("\tif (args_seri) {")

                for i in range(len(in_field_names)):
                    in_field_name = in_field_names[i]
                    arg = "{}".format(args[i])
                    getter_invoke = self._get_struct_field_getter_invoke("args_seri", in_field_name, arg, _ARGS_RESULT_SERI_SFA)

                    sb.wl("\t\t{};".format(getter_invoke))

                sb.wl("\t}")
                sb.we()

            indent = "\t"

            if has_excs:
                sb.wl("\ttry {")
                indent += "\t"

            # Always check method return value, even if it is declared as void.
            # If the method would like to do asynchronous execution, then
            # we have to check for ProcessorNotFinished return value.
            # Since we are in a try block, be sure that only the called functions
            # (this._impl.method, func) can throw exceptions.

            sb.wl("{}r = args_seri ? this._impl.{}({}) : func(user_data);".format(indent, name, argsf))

            if has_excs:
                sb.wl("\t} catch (e) {")

                for (i, exc) in enumerate(excs):
                    exc_name = exc.get_name()
                    exc_classn = self._get_dtype_classn(exc_name)

                    sb.wl("\t\t{} (e instanceof {}) {{".format("} else if" if i > 0 else "if", exc_classn))
                    sb.wl("\t\t\texc_name = \"{}\";".format(exc_name))
                    sb.wl("\t\t\texc = e;")

                sb.wl("\t\t} else {")
                sb.wl("\t\t\tthrow e;")
                sb.wl("\t\t}")
                sb.wl("\t}")

            sb.we()
            sb.wl("\thr = new myrpc.util.HandlerReturn();")
            sb.we()

            sb.wl("\tif (r instanceof myrpc.util.ProcessorNotFinishedClass) {")
            sb.wl("\t\thr.set_notfinished();")
            sb.wl("\t} else if (exc_name != null) {")
            sb.wl("\t\thr.set_exc(exc, exc_name);")
            sb.wl("\t} else {")
            sb.wl("\t\tresult_seri = new {}();".format(result_seri_classn))

            if has_result:
                setter_invoke = self._get_struct_field_setter_invoke("result_seri", RESULT_FIELD_NAME, "r", _ARGS_RESULT_SERI_SFA)
                sb.wl("\t\t{};".format(setter_invoke))

            sb.we()
            sb.wl("\t\thr.set_result(result_seri);")
            sb.wl("\t}")
            sb.we()

            sb.wl("\treturn hr;")
            sb.wl("};")
            sb.we()

        self._ws(sb.get_string())

    def _wheader_node(self, mods, create_ns):
        sb = StringBuilder()

        sb.wl("(function() {")
        sb.wl("var myrpc;")
        sb.wl("var {};".format(self._namespace))
        sb.we()
        sb.wl("myrpc = require(\"myrpc-runtime\");")

        for mod in mods:
            sb.wl("require(\"myrpc-runtime/lib/{}\");".format(mod))

        sb.we()
        sb.wl("{} = {};".format(self._namespace, "{}" if create_ns else "require(\"./{}\")".format(_TYPES_MODULE)))
        sb.we()
        sb.wl("module.exports = {};".format(self._namespace))
        sb.we()

        self._ws(sb.get_string())

    def _wfooter_node(self):
        self._strip_extra_nl()

        sb = StringBuilder()

        sb.wl("})();")

        self._ws(sb.get_string())

    def _setup_dtype_kinds(self):
        dtype_kinds = {
            DataTypeKind.BINARY: ("BINARY", self._dtype_kind_primitive_gen, self._dtype_kind_primitive_read, self._dtype_kind_primitive_write),
            DataTypeKind.STRING: ("STRING", self._dtype_kind_primitive_gen, self._dtype_kind_primitive_read, self._dtype_kind_primitive_write),
            DataTypeKind.BOOL:   ("BOOL",   self._dtype_kind_primitive_gen, self._dtype_kind_primitive_read, self._dtype_kind_primitive_write),
            DataTypeKind.UI8:    ("UI8",    self._dtype_kind_primitive_gen, self._dtype_kind_primitive_read, self._dtype_kind_primitive_write),
            DataTypeKind.UI16:   ("UI16",   self._dtype_kind_primitive_gen, self._dtype_kind_primitive_read, self._dtype_kind_primitive_write),
            DataTypeKind.UI32:   ("UI32",   self._dtype_kind_primitive_gen, self._dtype_kind_primitive_read, self._dtype_kind_primitive_write),
            DataTypeKind.UI64:   ("UI64",   self._dtype_kind_primitive_gen, self._dtype_kind_primitive_read, self._dtype_kind_primitive_write),
            DataTypeKind.I8:     ("I8",     self._dtype_kind_primitive_gen, self._dtype_kind_primitive_read, self._dtype_kind_primitive_write),
            DataTypeKind.I16:    ("I16",    self._dtype_kind_primitive_gen, self._dtype_kind_primitive_read, self._dtype_kind_primitive_write),
            DataTypeKind.I32:    ("I32",    self._dtype_kind_primitive_gen, self._dtype_kind_primitive_read, self._dtype_kind_primitive_write),
            DataTypeKind.I64:    ("I64",    self._dtype_kind_primitive_gen, self._dtype_kind_primitive_read, self._dtype_kind_primitive_write),
            DataTypeKind.FLOAT:  ("FLOAT",  self._dtype_kind_primitive_gen, self._dtype_kind_primitive_read, self._dtype_kind_primitive_write),
            DataTypeKind.DOUBLE: ("DOUBLE", self._dtype_kind_primitive_gen, self._dtype_kind_primitive_read, self._dtype_kind_primitive_write),
            DataTypeKind.ENUM:   ("ENUM",   self._dtype_kind_enum_gen,      self._dtype_kind_enum_read,      self._dtype_kind_enum_write),
            DataTypeKind.LIST:   ("LIST",   self._dtype_kind_list_gen,      self._dtype_kind_list_read,      self._dtype_kind_list_write),
            DataTypeKind.STRUCT: ("STRUCT", self._dtype_kind_struct_gen,    self._dtype_kind_struct_read,    self._dtype_kind_struct_write),
            # Exceptions are using the same methods as structs.
            DataTypeKind.EXC:    (None,     self._dtype_kind_struct_gen,    None,                            None)
        }

        self._register_dtype_kinds(dtype_kinds)

    def _dtype_kind_primitive_gen(self, dtype):
        # Primitive types don't need any generated serializer/deserializer code.

        return ""

    def _dtype_kind_primitive_read(self, dtype, v):
        sb = StringBuilder()
        dtype_name = dtype.get_name()

        sb.wl("{} = codec.read_{}();".format(v, dtype_name))

        return sb.get_string()

    def _dtype_kind_primitive_write(self, dtype, v):
        sb = StringBuilder()
        dtype_name = dtype.get_name()

        sb.wl("codec.write_{}({});".format(dtype_name, v))

        return sb.get_string()

    def _dtype_kind_enum_gen(self, dtype):
        sb = StringBuilder()
        dtype_name = dtype.get_name()
        entries = dtype.get_entries()
        values = dtype.get_values()
        classn = self._get_dtype_classn(dtype_name)
        read_funcn = self._get_enum_read_funcn(dtype_name)
        write_funcn = self._get_enum_write_funcn(dtype_name)
        validate_funcn = self._get_enum_validate_funcn(dtype_name)

        sb.wl("{} = {{".format(classn))

        lasti = len(entries) - 1

        for (i, (name, value)) in enumerate(entries):
            sb.wl("\t{}: {}{}".format(name, value, "," if i < lasti else ""))

        sb.wl("};")
        sb.we()

        sb.wl("{} = function(codec)".format(read_funcn))
        sb.wl("{")
        sb.wl("\tvar v = codec.read_i32();")
        sb.we()
        sb.wl("\t{}(true, v);".format(validate_funcn))
        sb.we()
        sb.wl("\treturn v;")
        sb.wl("};")
        sb.we()

        sb.wl("{} = function(codec, v)".format(write_funcn))
        sb.wl("{")
        sb.wl("\t{}(false, v);".format(validate_funcn))
        sb.we()
        sb.wl("\tcodec.write_i32(v);")
        sb.wl("};")
        sb.we()

        sb.wl("{} = function(is_read, v)".format(validate_funcn))
        sb.wl("{")
        sb.wl("\tvar msg;")

        valuesf = ", ".join(values)

        sb.wl("\tvar values = [{}];".format(valuesf))
        sb.we()

        sb.wl("\tif (values.indexOf(v) == -1) {")
        sb.wl("\t\tmsg = \"Enum {} unknown value \" + v;".format(dtype_name))
        sb.we()
        sb.wl("\t\tif (is_read)")
        sb.wl("\t\t\tthrow new myrpc.common.MessageBodyException(msg);")
        sb.wl("\t\telse")
        sb.wl("\t\t\tthrow new myrpc.common.MessageEncodeException(msg);")
        sb.wl("\t}")
        sb.wl("};")
        sb.we()

        return sb.get_string()

    def _dtype_kind_enum_read(self, dtype, v):
        sb = StringBuilder()
        dtype_name = dtype.get_name()
        funcn = self._get_enum_read_funcn(dtype_name)

        sb.wl("{} = {}(codec);".format(v, funcn))

        return sb.get_string()

    def _dtype_kind_enum_write(self, dtype, v):
        sb = StringBuilder()
        dtype_name = dtype.get_name()
        funcn = self._get_enum_write_funcn(dtype_name)

        sb.wl("{}(codec, {});".format(funcn, v))

        return sb.get_string()

    def _dtype_kind_list_gen(self, dtype):
        sb = StringBuilder()
        dtype_name = dtype.get_name()
        elem_dtype = dtype.get_elem_dtype()
        read_funcn = self._get_list_read_funcn(dtype_name)
        write_funcn = self._get_list_write_funcn(dtype_name)
        codec_dtype_classn = self._get_codec_dtype_classn(elem_dtype)

        sb.wl("{} = function(codec)".format(read_funcn))
        sb.wl("{")
        sb.wl("\tvar linfo;")
        sb.wl("\tvar llen;")
        sb.wl("\tvar dtype;")
        sb.wl("\tvar i;")
        sb.wl("\tvar elem;")
        sb.wl("\tvar l = [];")
        sb.we()
        sb.wl("\tlinfo = codec.read_list_begin();")
        sb.wl("\tllen = linfo[0];")
        sb.wl("\tdtype = linfo[1];")
        sb.we()
        sb.wl("\tif (dtype != {})".format(codec_dtype_classn))
        sb.wl("\t\tthrow new myrpc.common.MessageBodyException(\"List {} has unexpected elem data type \" + dtype);".format(dtype_name))
        sb.we()
        sb.wl("\tfor (i = 0; i < llen; i++) {")

        s = self._gtm.read_dtype(elem_dtype, "elem")
        sb.wlsindent("\t\t", s)

        sb.wl("\t\tl.push(elem);")
        sb.wl("\t}")
        sb.we()
        sb.wl("\tcodec.read_list_end();")
        sb.we()
        sb.wl("\treturn l;")
        sb.wl("};")
        sb.we()

        sb.wl("{} = function(codec, l)".format(write_funcn))
        sb.wl("{")
        sb.wl("\tcodec.write_list_begin(l.length, {});".format(codec_dtype_classn))
        sb.we()
        sb.wl("\tl.forEach(function(elem) {")

        s = self._gtm.write_dtype(elem_dtype, "elem")
        sb.wlsindent("\t\t", s)

        sb.wl("\t});")
        sb.we()
        sb.wl("\tcodec.write_list_end();")
        sb.wl("};")
        sb.we()

        return sb.get_string()

    def _dtype_kind_list_read(self, dtype, v):
        sb = StringBuilder()
        dtype_name = dtype.get_name()
        funcn = self._get_list_read_funcn(dtype_name)

        sb.wl("{} = {}(codec);".format(v, funcn))

        return sb.get_string()

    def _dtype_kind_list_write(self, dtype, v):
        sb = StringBuilder()
        dtype_name = dtype.get_name()
        funcn = self._get_list_write_funcn(dtype_name)

        sb.wl("{}(codec, {});".format(funcn, v))

        return sb.get_string()

    def _dtype_kind_struct_gen(self, dtype, classn = None, sfa = None):
        sb = StringBuilder()
        dtype_name = dtype.get_name()
        fields = dtype.get_fields()

        # We have the option to override classname, it is used
        # during method args_seri/result_seri generation (these are
        # structs).

        if classn == None:
            classn = self._get_dtype_classn(dtype_name)

        # Do we need to generate validation method?

        is_validate_needed = False
        for field in fields:
            if field.get_req():
                is_validate_needed = True
                break

        if sfa == None:
            sfa = self._sfa

        sb.wl("{} = function()".format(classn))
        sb.wl("{")

        for field in fields:
            name = field.get_name()
            var_name = self._get_struct_field_var_name(name, sfa)

            sb.wl("\t{} = null;".format(var_name))

        sb.wl("};")
        sb.we()

        # Generate setter/getter methods.

        self._sfa_check_start(dtype_name)

        for field in fields:
            name = field.get_name()
            var_name = self._get_struct_field_var_name(name, sfa)
            getter_name = self._get_struct_field_getter_name(name, sfa)
            setter_name = self._get_struct_field_setter_name(name, sfa)

            if getter_name != None:
                self._sfa_check_name(getter_name)

                sb.wl("{}.prototype.{} = function()".format(classn, getter_name))
                sb.wl("{")
                sb.wl("\treturn {};".format(var_name))
                sb.wl("};")
                sb.we()

            if setter_name != None:
                self._sfa_check_name(setter_name)

                sb.wl("{}.prototype.{} = function({})".format(classn, setter_name, name))
                sb.wl("{")
                sb.wl("\t{} = {};".format(var_name, name))
                sb.wl("};")
                sb.we()

        # Generate serializer, deserializer and validator methods.

        sb.wl("{}.prototype.{} = function(codec)".format(classn, _STRUCT_READ))
        sb.wl("{")
        sb.wl("\tvar finfo;")
        sb.wl("\tvar fid;")
        sb.wl("\tvar dtype;")
        sb.wl("\tvar err_dtype;")
        sb.wl("\tvar err_dup;")
        sb.we()
        sb.wl("\tcodec.read_struct_begin();")
        sb.we()
        sb.wl("\twhile (true) {")
        sb.wl("\t\tfinfo = codec.read_field_begin();")
        sb.wl("\t\tfid = finfo[0];")
        sb.wl("\t\tdtype = finfo[1];")
        sb.wl("\t\terr_dtype = false;")
        sb.wl("\t\terr_dup = false;")
        sb.we()
        sb.wl("\t\tif (fid == myrpc.codec.FID_STOP)")
        sb.wl("\t\t\tbreak;")
        sb.we()
        sb.wl("\t\tswitch (fid) {")

        for field in fields:
            fid = field.get_fid()
            field_dtype = field.get_dtype()
            name = field.get_name()
            var_name = self._get_struct_field_var_name(name, sfa)
            codec_dtype_classn = self._get_codec_dtype_classn(field_dtype)

            sb.wl("\t\t\tcase {}:".format(fid))
            sb.wl("\t\t\t\tif (dtype != {}) {{".format(codec_dtype_classn))
            sb.wl("\t\t\t\t\terr_dtype = true;")
            sb.wl("\t\t\t\t}} else if ({} != null) {{".format(var_name))
            sb.wl("\t\t\t\t\terr_dup = true;")
            sb.wl("\t\t\t\t} else {")

            s = self._gtm.read_dtype(field_dtype, var_name)
            sb.wlsindent("\t\t\t\t\t", s)

            sb.wl("\t\t\t\t}")
            sb.wl("\t\t\t\tbreak;")
            sb.we()

        sb.wl("\t\t\tdefault:")
        sb.wl("\t\t\t\tthrow new myrpc.common.MessageBodyException(\"Struct {} unknown fid \" + fid);".format(dtype_name))
        sb.wl("\t\t}")
        sb.we()
        sb.wl("\t\tif (err_dtype)")
        sb.wl("\t\t\tthrow new myrpc.common.MessageBodyException(\"Struct {} fid \" + fid + \" has unexpected data type \" + dtype);".format(dtype_name))
        sb.wl("\t\telse if (err_dup)")
        sb.wl("\t\t\tthrow new myrpc.common.MessageBodyException(\"Struct {} fid \" + fid + \" is duplicated\");".format(dtype_name))
        sb.we()
        sb.wl("\t\tcodec.read_field_end();")
        sb.wl("\t}")
        sb.we()
        sb.wl("\tcodec.read_struct_end();")

        if is_validate_needed:
            sb.we()
            sb.wl("\tthis.{}(true);".format(_STRUCT_VALIDATE))

        sb.wl("};")
        sb.we()

        sb.wl("{}.prototype.{} = function(codec)".format(classn, _STRUCT_WRITE))
        sb.wl("{")

        if is_validate_needed:
            sb.wl("\tthis.{}(false);".format(_STRUCT_VALIDATE))
            sb.we()

        sb.wl("\tcodec.write_struct_begin();")
        sb.we()

        for field in fields:
            fid = field.get_fid()
            req = field.get_req()
            field_dtype = field.get_dtype()
            name = field.get_name()
            var_name = self._get_struct_field_var_name(name, sfa)
            codec_dtype_classn = self._get_codec_dtype_classn(field_dtype)

            indent = "\t"

            if not req:
                sb.wl("\tif ({} != null) {{".format(var_name))
                indent += "\t"

            sb.wl("{}codec.write_field_begin({}, {});".format(indent, fid, codec_dtype_classn))

            s = self._gtm.write_dtype(field_dtype, var_name)
            sb.wlsindent(indent, s)

            sb.wl("{}codec.write_field_end();".format(indent))

            if not req:
                sb.wl("\t}")

            sb.we()

        sb.wl("\tcodec.write_field_stop();")
        sb.we()
        sb.wl("\tcodec.write_struct_end();")
        sb.wl("};")
        sb.we()

        if is_validate_needed:
            sb.wl("{}.prototype.{} = function(is_read)".format(classn, _STRUCT_VALIDATE))
            sb.wl("{")
            sb.wl("\tvar msg;")
            sb.wl("\tvar name = null;")
            sb.we()

            i = 0

            for field in fields:
                req = field.get_req()
                name = field.get_name()
                var_name = self._get_struct_field_var_name(name, sfa)

                if req:
                    sb.wl("\t{} ({} == null)".format("else if" if i > 0 else "if", var_name))
                    sb.wl("\t\tname = \"{}\";".format(name))

                    i += 1

            sb.we()
            sb.wl("\tif (name != null) {")
            sb.wl("\t\tmsg = \"Struct {} field \" + name + \" is null\";".format(dtype_name))
            sb.we()
            sb.wl("\t\tif (is_read)")
            sb.wl("\t\t\tthrow new myrpc.common.MessageBodyException(msg);")
            sb.wl("\t\telse")
            sb.wl("\t\t\tthrow new myrpc.common.MessageEncodeException(msg);")
            sb.wl("\t}")

            sb.wl("};")
            sb.we()

        return sb.get_string()

    def _dtype_kind_struct_read(self, dtype, v):
        sb = StringBuilder()
        dtype_name = dtype.get_name()
        classn = self._get_dtype_classn(dtype_name)

        sb.wl("{} = new {}();".format(v, classn))
        sb.wl("{}.{}(codec);".format(v, _STRUCT_READ))

        return sb.get_string()

    def _dtype_kind_struct_write(self, dtype, v):
        sb = StringBuilder()

        sb.wl("{}.{}(codec);".format(v, _STRUCT_WRITE))

        return sb.get_string()

    def _get_dtype_classn(self, name):
        classn = "{}.{}".format(self._dtype_classp, name)

        return classn

    def _get_enum_read_funcn(self, name):
        funcn = "{}_{}".format(self._enum_read_funcp, name)

        return funcn

    def _get_enum_write_funcn(self, name):
        funcn = "{}_{}".format(self._enum_write_funcp, name)

        return funcn

    def _get_enum_validate_funcn(self, name):
        funcn = "{}_{}".format(self._enum_validate_funcp, name)

        return funcn

    def _get_list_read_funcn(self, name):
        funcn = "{}_{}".format(self._list_read_funcp, name)

        return funcn

    def _get_list_write_funcn(self, name):
        funcn = "{}_{}".format(self._list_write_funcp, name)

        return funcn

    def _get_args_seri_classn(self, name):
        classn = "{}_{}".format(self._args_seri_classp, name)

        return classn

    def _get_result_seri_classn(self, name):
        classn = "{}_{}".format(self._result_seri_classp, name)

        return classn

    def _get_codec_dtype_classn(self, dtype):
        codec_dtype = self._gtm.get_codec_dtype(dtype)
        if codec_dtype == None:
            raise InternalException("codec_dtype is None")

        classn = "{}.{}".format(self._codec_dtype_classp, codec_dtype)

        return classn

    def _get_exc_handler_funcn(self, name):
        funcn = "{}_{}".format(self._exc_handler_funcp, name)

        return funcn

GeneratorBase.register_gen("js", JSGenerator)
