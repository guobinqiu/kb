from .apps import AppsDAO
from .files import FilesDAO
from .orgs import OrgsDAO
from .users import UsersDAO
from .workspaces import WorkspacesDAO


class PostgresDAO(AppsDAO, OrgsDAO, UsersDAO, WorkspacesDAO, FilesDAO):
    pass
