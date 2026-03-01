"""Internal helpers — class property descriptor and SQLAlchemy enum type."""

from enum import Enum, IntFlag, IntEnum
from typing import Optional, Any, Type, Callable
from sqlalchemy import TypeDecorator
from sqlalchemy import Integer, String


class classproperty:
    """Descriptor that converts a method into a class-level read-only property.

    Usage is analogous to the built-in ``@property`` decorator but operates
    on the class rather than an instance.
    """

    def __init__(self, func: Callable[..., Any]) -> None:
        """Initialise the class property.

        :param func: The callable to expose as a class property.
        """
        self._func = func

    def __get__(self, _: Any, instance: Any) -> Any:
        """Return the result of calling the wrapped function on the owner class.

        :param _: Unused instance reference.
        :param instance: The owner class.
        :returns: The value produced by the wrapped callable.
        :rtype: Any
        """
        return self._func(instance)


class SqlValueEnum(TypeDecorator[Enum]):
    """SQLAlchemy type decorator that stores a Python enum's *value* in the database.

    By default SQLAlchemy would persist the enum member's *name* (a string).
    This decorator ensures the underlying integer (or other scalar) value is
    stored instead.
    """

    impl = Integer
    cache_ok = True

    def __init__(
            self,
            enumtype: Type[Enum],
            *args: Any,
            **kwargs: Any
            ) -> None:
        """Initialise the type decorator for a specific enum type.

        Automatically selects :class:`String` as the underlying column
        type when the enum's values are strings, and :class:`Integer`
        otherwise.

        :param enumtype: The enum class whose values will be stored.
        :param args: Positional arguments forwarded to the base
            :class:`TypeDecorator`.
        :param kwargs: Keyword arguments forwarded to the base
            :class:`TypeDecorator`.
        """
        super(SqlValueEnum, self).__init__(*args, **kwargs)
        self._enumtype: Type[Enum] = enumtype

        # Auto-detect impl type based on enum member values
        sample = next(iter(enumtype), None)
        if sample is not None and isinstance(sample.value, str):
            self.impl = String()

    def process_bind_param(self, value: Optional[Enum], dialect: Any) -> Any:
        """Convert a Python enum member to its database representation.

        :param value: The enum member to persist, or ``None``.
        :param dialect: The active SQLAlchemy dialect.
        :returns: The enum member's scalar value, or ``None``.
        :rtype: Any
        :raises ValueError: If the enum is an integer type and *value* is
            ``None``.
        """
        if issubclass(self._enumtype, (IntFlag, IntEnum)):
            if value is None:
                raise ValueError("An integer enum cannot be nullable.")

        if value is None:
            return value

        return value.value

    def process_result_value(self, value: Optional[Any], dialect: Any) -> Optional[Enum]:
        """Convert a database value back to the corresponding Python enum member.

        :param value: The raw database value.
        :param dialect: The active SQLAlchemy dialect.
        :returns: The matching enum member.
        :rtype: Enum
        :raises ValueError: If *value* does not correspond to any member of
            the enum.
        """
        if value is None:
            return None

        if value in self._enumtype:
            return self._enumtype(value)

        for e in self._enumtype:
            if e.value == value:
                return e

        raise ValueError(f"Not an {self._enumtype}: {value}")
