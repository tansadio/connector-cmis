# © 2016 ACSONE SA/NV (<http://acsone.eu>).
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo.exceptions import UserError


class CMISError(UserError):
    """CMIS Error!

    :param cmis_exception: name of the CMIS exception returned by the server
        (``objectNotFound``, ``contentAlreadyExists``...), if any
    :param status_code: HTTP status code of the response, if any
    """

    def __init__(self, value, cmis_exception=None, status_code=None):
        super().__init__(value)
        self.cmis_exception = cmis_exception
        self.status_code = status_code


class CMISConnectionError(CMISError):
    """The CMIS server can not be reached or authentication failed"""


class CMISObjectNotFoundError(CMISError):
    """CMIS ``objectNotFound`` exception"""


class CMISContentAlreadyExistsError(CMISError):
    """CMIS ``contentAlreadyExists`` or ``nameConstraintViolation`` exception"""


class CMISPermissionDeniedError(CMISError):
    """CMIS ``permissionDenied`` exception"""


class CMISUpdateConflictError(CMISError):
    """CMIS ``updateConflict`` exception"""


class CMISVersioningError(CMISError):
    """CMIS ``versioning`` exception"""


# CMIS exception names, as returned by the browser binding (CMIS 1.1 §5.2.9)
CMIS_EXCEPTIONS = {
    "objectNotFound": CMISObjectNotFoundError,
    "contentAlreadyExists": CMISContentAlreadyExistsError,
    "nameConstraintViolation": CMISContentAlreadyExistsError,
    "permissionDenied": CMISPermissionDeniedError,
    "updateConflict": CMISUpdateConflictError,
    "versioning": CMISVersioningError,
}
