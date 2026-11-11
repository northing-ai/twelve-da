"""Bounded uncertainty for retaining source arcs, never geometry repair."""
import math
import re
from fractions import Fraction

ARC_DIAGNOSTIC = 'precision-limited arc'
MAX_RELATIVE_UNCERTAINTY = Fraction(1, 1_000_000)
EXACT_COORDINATE = 32767
UNKNOWN_COORDINATE = 32766


def arc_exceeds_diameter(coordinates, start, end, radius):
    """Exact predicate on retained float64 values; no relative epsilon bypass."""
    dx = Fraction(coordinates[start]) - Fraction(coordinates[end])
    dy = Fraction(coordinates[start+1]) - Fraction(coordinates[end+1])
    return dx*dx + dy*dy > 4*Fraction(radius)**2


def export_decimal_places(header):
    """Only one valid leading declaration may qualify a decimal export."""
    values = [field.value for field in header if field.key == 'decimal_places']
    if len(values) != 1 or not re.fullmatch(r'(?:[0-9]|1[0-5])', values[0]):
        return None
    return int(values[0])


def arc_rounding_bound(data, declared_places, start, end, coordinates, radius):
    """Return an uncertainty bound only for sufficiently precise decimal XY.

    Each coordinate can differ by half a printed last place; differences of two
    endpoints can therefore differ by one place per axis. Include decimal input
    conversion error; hexadecimal values are exact. Exact rational arithmetic
    checks the endpoint rectangles. A per-axis cap rejects coarse/ill-conditioned
    data rather than turning the bound into a general-purpose geometry tolerance.
    """
    lexical_places = getattr(data, 'decimal_places', None)
    if declared_places is None or lexical_places is None:
        return None
    diameter = 2*abs(Fraction(radius))
    uncertainty, minimum_deltas = [], []
    decimal_uncertainty = False
    for axis in (0, 1):
        a, b = coordinates[start+axis], coordinates[end+axis]
        delta = Fraction(a)-Fraction(b)
        error = Fraction(0)
        for vertex, value in ((start//3, a), (end//3, b)):
            places = lexical_places[2*vertex+axis]
            if places == UNKNOWN_COORDINATE:
                return None
            if places != EXACT_COORDINATE:
                error += Fraction(1, 2*10**max(declared_places, places))
                error += Fraction(math.ulp(value))/2
                decimal_uncertainty = True
        uncertainty.append(error)
        minimum_deltas.append(max(Fraction(0), abs(delta)-error))
    if not decimal_uncertainty or max(uncertainty) > diameter * MAX_RELATIVE_UNCERTAINTY:
        return None
    # The endpoint rounding rectangles must actually permit a chord <= diameter;
    # a generic vector-error envelope alone can admit an impossible axis-aligned arc.
    if sum(value*value for value in minimum_deltas) > diameter*diameter:
        return None
    return math.hypot(*(float(value) for value in uncertainty))
