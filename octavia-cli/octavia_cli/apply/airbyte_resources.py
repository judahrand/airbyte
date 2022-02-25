#
# Copyright (c) 2021 Airbyte, Inc., all rights reserved.
#

import abc
from typing import Any, Callable

import airbyte_api_client
import yaml
from airbyte_api_client.api import destination_api, source_api
from airbyte_api_client.model.destination_create import DestinationCreate
from airbyte_api_client.model.destination_search import DestinationSearch
from airbyte_api_client.model.destination_update import DestinationUpdate
from airbyte_api_client.model.source_create import SourceCreate
from airbyte_api_client.model.source_search import SourceSearch
from airbyte_api_client.model.source_update import SourceUpdate
from click import ClickException
from deepdiff import DeepDiff


class DuplicateRessourceError(ClickException):
    pass


class InvalidConfigurationError(ClickException):
    pass


class BaseAirbyteResource(abc.ABC):
    @property
    @abc.abstractmethod
    def api(
        self,
    ):  # pragma: no cover
        pass

    @property
    @abc.abstractmethod
    def create_function_name(
        self,
    ):  # pragma: no cover
        pass

    @property
    @abc.abstractmethod
    def update_function_name(
        self,
    ):  # pragma: no cover
        pass

    @property
    @abc.abstractmethod
    def search_function_name(
        self,
    ):  # pragma: no cover
        pass

    @property
    @abc.abstractmethod
    def create_payload(
        self,
    ):  # pragma: no cover
        pass

    @property
    @abc.abstractmethod
    def search_payload(
        self,
    ):  # pragma: no cover
        pass

    @property
    @abc.abstractmethod
    def update_payload(
        self,
    ):  # pragma: no cover
        pass

    @property
    @abc.abstractmethod
    def resource_id_field(
        self,
    ):  # pragma: no cover
        pass

    @property
    def _create_fn(self) -> Callable:
        return getattr(self.api, self.create_function_name)

    @property
    def _update_fn(self) -> Callable:
        return getattr(self.api, self.update_function_name)

    @property
    def _search_fn(self) -> Callable:
        return getattr(self.api, self.search_function_name)

    def __init__(self, api_client: airbyte_api_client.ApiClient, workspace_id, yaml_config: dict) -> None:
        self.workspace_id = workspace_id
        self._yaml_config = yaml_config
        self.api_instance = self.api(api_client)

    def get_connection_configuration_diff(self):
        current_config = self.configuration
        if self.remote_resource is not None:
            remote_config = self.remote_resource.connection_configuration

        diff = DeepDiff(remote_config, current_config, view="tree")
        return diff.pretty()

    def __getattr__(self, name: str) -> Any:
        """Map attribute of the YAML config to the BaseAirbyteResource object.

        Args:
            name (str): Attribute name

        Raises:
            AttributeError: Raised if the attributed was not found in the API response payload.

        Returns:
            [Any]: Attribute value
        """
        if name in self._yaml_config:
            return self._yaml_config.get(name)
        raise AttributeError(f"{self.__class__.__name__}.{name} is invalid.")

    def _create_or_update(self, operation_fn, payload):
        try:
            return operation_fn(self.api_instance, payload)
        except airbyte_api_client.ApiException as e:
            if e.status == 422:
                # TODO alafanechere: provide link to JSON schema / documentation?
                raise InvalidConfigurationError(
                    "Your configuration is invalid, please make sure it complies with the connector definitions."
                )
            else:
                raise e

    def create(self):
        return self._create_or_update(self._create_fn, self.create_payload)

    def update(self):
        return self._create_or_update(self._update_fn, self.update_payload)

    def _search(self):
        return self._search_fn(self.api_instance, self.search_payload)

    @property
    def remote_resource(self):
        search_results = self._search()
        if len(search_results.sources) > 1:
            raise DuplicateRessourceError("Two or more ressource exist with the same name")
        if len(search_results.sources) == 1:
            return search_results.sources[0]
        else:
            return None

    @property
    def exists(self):
        return True if self.remote_resource else False

    @property
    def resource_id(self):
        return self.remote_resource.get(self.resource_id_field)


class Source(BaseAirbyteResource):

    api = source_api.SourceApi
    create_function_name = "create_source"
    resource_id_field = "source_id"
    search_function_name = "search_sources"
    update_function_name = "update_source"

    @property
    def create_payload(self):
        return SourceCreate(self.definition_id, self.configuration, self.workspace_id, self.resource_name)

    @property
    def search_payload(self):
        return SourceSearch(source_definition_id=self.definition_id, workspace_id=self.workspace_id, name=self.resource_name)

    @property
    def update_payload(self):
        return SourceUpdate(
            source_id=self.resource_id,
            connection_configuration=self.configuration,
            name=self.resource_name,
        )


class Destination(BaseAirbyteResource):
    api = destination_api.DestinationApi
    create_function_name = "create_destination"
    resource_id_field = "destination_id"
    search_function_name = "search_destinations"
    update_function_name = "update_destination"

    @property
    def create_payload(self):
        return DestinationCreate(self.definition_id, self.configuration, self.workspace_id, self.resource_name)

    @property
    def search_payload(self):
        return DestinationSearch(destination_definition_id=self.definition_id, workspace_id=self.workspace_id, name=self.resource_name)

    @property
    def update_payload(self):
        return DestinationUpdate(
            destination_id=self.resource_id,
            connection_configuration=self.configuration,
            name=self.resource_name,
        )


def factory(api_client, workspace_id, yaml_file_path):
    with open(yaml_file_path, "r") as f:
        yaml_config = yaml.load(f, yaml.FullLoader)
    if yaml_config["definition_type"] == "source":
        AirbyteResource = Source
    if yaml_config["definition_type"] == "destination":
        AirbyteResource = Destination
    return AirbyteResource(api_client, workspace_id, yaml_config)