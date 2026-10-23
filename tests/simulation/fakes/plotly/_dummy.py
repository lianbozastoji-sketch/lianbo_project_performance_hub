"""Recording stand-in for plotly used by the simulation.

Real plotly raises ValueError for an unknown property; this fake does the same
check for the properties the app uses, so a typo in chart code is caught in the
simulation even though plotly itself is not installed here. Problems are
collected in PROBLEMS (the simulation asserts it stays empty).
"""

PROBLEMS = []

_COMMON_TRACE = {
    "x", "y", "name", "showlegend", "customdata", "hovertext", "hovertemplate", "hoverinfo", "text", "textposition",
    "textfont", "texttemplate", "marker", "opacity", "legendgroup", "visible", "xaxis", "yaxis", "selectedpoints",
    "selected", "unselected", "meta", "uid", "ids", "hoverlabel", "textangle",
}
_TRACE_PROPS = {
    "Bar": _COMMON_TRACE | {"base", "width", "orientation", "cliponaxis", "offset", "offsetgroup", "insidetextanchor",
                            "error_y", "error_x", "constraintext", "outsidetextfont", "insidetextfont", "alignmentgroup"},
    "Scatter": _COMMON_TRACE | {"mode", "line", "connectgaps", "fill", "fillcolor", "cliponaxis", "line_shape", "stackgroup"},
    "Pie": {"labels", "values", "hole", "marker", "textinfo", "textposition", "hovertemplate", "sort", "direction",
            "showlegend", "name", "textfont", "insidetextorientation", "pull", "rotation", "customdata", "hoverinfo",
            "texttemplate", "domain", "title", "outsidetextfont", "insidetextfont", "automargin"},
    "Indicator": {"mode", "value", "title", "gauge", "number", "delta", "domain"},
}
_MARKER = {"color", "line", "size", "symbol", "opacity", "colorscale", "pattern", "cornerradius", "colors", "showscale",
           "cmin", "cmax", "colorbar"}
_MARKER_LINE = {"color", "width"}
_LINE = {"color", "width", "dash", "shape", "smoothing", "simplify"}
_TEXTPOSITION = {
    "Bar": {"inside", "outside", "auto", "none"},
    "Scatter": {"top left", "top center", "top right", "middle left", "middle center", "middle right",
                "bottom left", "bottom center", "bottom right"},
}
_LAYOUT = {
    "title", "height", "width", "barmode", "showlegend", "clickmode", "margin", "template", "paper_bgcolor",
    "plot_bgcolor", "colorway", "font", "legend", "hoverlabel", "separators", "xaxis", "yaxis", "yaxis2", "xaxis2",
    "bargap", "bargroupgap", "dragmode", "annotations", "shapes", "hovermode", "uniformtext", "autosize", "polar",
    "transition", "modebar", "selectdirection", "barnorm", "piecolorway", "coloraxis", "grid", "images",
    "updatemenus", "sliders", "meta", "datarevision", "uirevision", "spikedistance", "hoverdistance",
}
_AXIS = {
    "type", "categoryorder", "categoryarray", "tickangle", "range", "tickvals", "ticktext", "ticksuffix", "tickprefix",
    "title", "title_text", "title_font", "showgrid", "gridcolor", "griddash", "gridwidth", "zeroline", "zerolinecolor",
    "showline", "linecolor", "linewidth", "ticks", "tickcolor", "tickfont", "dtick", "tick0", "automargin",
    "autorange", "fixedrange", "rangemode", "tickformat", "side", "overlaying", "showticklabels", "nticks",
    "tickmode", "mirror", "domain", "anchor", "showspikes", "matches", "visible", "ticklen", "tickwidth",
    "separatethousands", "exponentformat", "hoverformat", "layer", "position", "scaleanchor", "constrain",
}
_SHAPE = {"type", "xref", "yref", "x0", "x1", "y0", "y1", "fillcolor", "line", "layer", "opacity", "editable", "name",
          "path", "visible", "label"}
_ANNOTATION = {"xref", "yref", "x", "y", "xanchor", "yanchor", "text", "showarrow", "font", "align", "bgcolor",
               "bordercolor", "borderwidth", "borderpad", "yshift", "xshift", "ax", "ay", "arrowhead", "opacity",
               "arrowcolor", "arrowwidth", "valign", "textangle", "width", "height", "visible", "captureevents"}
_ENUMS = {
    ("layout", "barmode"): {"stack", "group", "overlay", "relative"},
    ("layout", "clickmode"): {"event", "select", "event+select", "none"},
    ("layout", "dragmode"): {"zoom", "pan", "select", "lasso", "orbit", "turntable", False, "drawclosedpath",
                             "drawopenpath", "drawline", "drawrect", "drawcircle", "erasershape"},
    ("axis", "type"): {"-", "linear", "log", "date", "category", "multicategory"},
    ("axis", "categoryorder"): {"trace", "category ascending", "category descending", "array", "total ascending",
                                "total descending", "min ascending", "max ascending", "sum ascending", "mean ascending",
                                "min descending", "max descending", "sum descending", "mean descending",
                                "median ascending", "median descending"},
    ("shape", "layer"): {"below", "above", "between"},
    ("shape", "type"): {"rect", "line", "circle", "path"},
    ("Bar", "orientation"): {"h", "v"},
}


def _problem(where, message):
    PROBLEMS.append(f"{where}: {message}")


def _check_keys(where, given, allowed):
    for key in given:
        root = key.split("_")[0] if key not in allowed else key
        if key not in allowed and root not in allowed:
            _problem(where, f"unknown property '{key}'")


def _check_enum(scope, key, value):
    allowed = _ENUMS.get((scope, key))
    if allowed is not None and value not in allowed:
        _problem(scope, f"invalid value {value!r} for '{key}'")


def _check_ref(where, ref):
    if ref is None:
        return
    text = str(ref)
    ok = text == "paper" or text.split(" ")[0].rstrip("0123456789") in ("x", "y")
    if not ok:
        _problem(where, f"invalid reference {ref!r}")


def _check_trace(kind, kwargs):
    allowed = _TRACE_PROPS.get(kind)
    if allowed is None:
        return
    _check_keys(kind, kwargs, allowed)
    for state_key in ("selected", "unselected"):
        if isinstance(kwargs.get(state_key), dict):
            _check_keys(f"{kind}.{state_key}", kwargs[state_key], {"marker", "textfont"})
            if isinstance(kwargs[state_key].get("marker"), dict):
                _check_keys(f"{kind}.{state_key}.marker", kwargs[state_key]["marker"], {"opacity", "color", "size"})
    marker = kwargs.get("marker")
    if isinstance(marker, dict):
        _check_keys(f"{kind}.marker", marker, _MARKER)
        if isinstance(marker.get("line"), dict):
            _check_keys(f"{kind}.marker.line", marker["line"], _MARKER_LINE)
    if isinstance(kwargs.get("line"), dict):
        _check_keys(f"{kind}.line", kwargs["line"], _LINE)
    if "textposition" in kwargs and kind in _TEXTPOSITION:
        positions = kwargs["textposition"]
        for position in positions if isinstance(positions, (list, tuple)) else [positions]:
            if position not in _TEXTPOSITION[kind]:
                _problem(kind, f"invalid textposition {position!r}")
    if "orientation" in kwargs:
        _check_enum(kind, "orientation", kwargs["orientation"])
    for key in ("x", "y", "customdata", "text", "hovertext", "base"):
        value = kwargs.get(key)
        if isinstance(value, (list, tuple)) and isinstance(kwargs.get("x"), (list, tuple)):
            if key != "x" and len(value) != len(kwargs["x"]) and kind in ("Bar", "Scatter"):
                _problem(kind, f"'{key}' has {len(value)} items but x has {len(kwargs['x'])}")


def _check_axis(where, kwargs):
    _check_keys(where, kwargs, _AXIS)
    for key in ("type", "categoryorder"):
        if key in kwargs:
            _check_enum("axis", key, kwargs[key])
    if "range" in kwargs and kwargs["range"] is not None:
        rng = kwargs["range"]
        if not (isinstance(rng, (list, tuple)) and len(rng) == 2):
            _problem(where, f"range must have two values: {rng!r}")


class Trace(dict):
    def __init__(self, kind, kwargs):
        super().__init__(kwargs)
        self.kind = kind


class Figure:
    """Accepts plotly calls, validates the important ones, records traces."""

    def __init__(self, *args, **kwargs):
        self.data = list(args[0]) if args and isinstance(args[0], (list, tuple)) else ([args[0]] if args else [])
        self.layout = {}
        self.shapes = []
        self.annotations = []

    def add_trace(self, trace, *args, **kwargs):
        self.data.append(trace)
        return self

    def update_layout(self, *args, **kwargs):
        if args and isinstance(args[0], dict):
            kwargs = {**args[0], **kwargs}
        _check_keys("layout", kwargs, _LAYOUT)
        for key in ("barmode", "clickmode", "dragmode"):
            if key in kwargs:
                _check_enum("layout", key, kwargs[key])
        for axis in ("xaxis", "yaxis", "yaxis2"):
            if isinstance(kwargs.get(axis), dict):
                _check_axis(f"layout.{axis}", kwargs[axis])
        self.layout.update(kwargs)
        return self

    def update_xaxes(self, *args, **kwargs):
        _check_axis("xaxes", kwargs)
        return self

    def update_yaxes(self, *args, **kwargs):
        _check_axis("yaxes", kwargs)
        return self

    def add_shape(self, *args, **kwargs):
        _check_keys("shape", kwargs, _SHAPE)
        for key in ("type", "layer"):
            if key in kwargs:
                _check_enum("shape", key, kwargs[key])
        _check_ref("shape.xref", kwargs.get("xref"))
        _check_ref("shape.yref", kwargs.get("yref"))
        if isinstance(kwargs.get("line"), dict):
            _check_keys("shape.line", kwargs["line"], _LINE)
        self.shapes.append(kwargs)
        return self

    def add_annotation(self, *args, **kwargs):
        _check_keys("annotation", kwargs, _ANNOTATION)
        _check_ref("annotation.xref", kwargs.get("xref"))
        _check_ref("annotation.yref", kwargs.get("yref"))
        self.annotations.append(kwargs)
        return self

    def __getattr__(self, name):
        def method(*args, **kwargs):
            return self
        return method


def _trace_factory(kind):
    def ctor(*args, **kwargs):
        _check_trace(kind, kwargs)
        return Trace(kind, kwargs)
    return ctor


def _factory(*args, **kwargs):
    return Figure()
