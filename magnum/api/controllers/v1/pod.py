#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import datetime

import pecan
from pecan import rest
import wsme
from wsme import types as wtypes
import wsmeext.pecan as wsme_pecan

from magnum.api.controllers import base
from magnum.api.controllers import link
from magnum.api.controllers.v1 import collection
from magnum.api.controllers.v1 import types
from magnum.api.controllers.v1 import utils as api_utils
from magnum.common import exception
from magnum import objects


class PodPatchType(types.JsonPatchType):

    @staticmethod
    def mandatory_attrs():
        return ['/pod_uuid']


class Pod(base.APIBase):
    """API representation of a pod.

    This class enforces type checking and value constraints, and converts
    between the internal object model and the API representation of a pod.
    """

    _pod_uuid = None

    def _get_pod_uuid(self):
        return self._pod_uuid

    def _set_pod_uuid(self, value):
        if value and self._pod_uuid != value:
            try:
                # FIXME(comstud): One should only allow UUID here, but
                # there seems to be a bug in that tests are passing an
                # ID. See bug #1301046 for more details.
                pod = objects.Pod.get(pecan.request.context, value)
                self._pod_uuid = pod.uuid
                # NOTE(lucasagomes): Create the pod_id attribute on-the-fly
                #                    to satisfy the api -> rpc object
                #                    conversion.
                self.pod_id = pod.id
            except exception.PodNotFound as e:
                # Change error code because 404 (NotFound) is inappropriate
                # response for a POST request to create a Pod
                e.code = 400  # BadRequest
                raise e
        elif value == wtypes.Unset:
            self._pod_uuid = wtypes.Unset

    uuid = types.uuid
    """Unique UUID for this pod"""

    name = wtypes.text
    """Name of this pod"""

    desc = wtypes.text
    """Description of this pod"""

    bay_uuid = types.uuid
    """Unique UUID of the bay the pod runs on"""

    links = wsme.wsattr([link.Link], readonly=True)
    """A list containing a self link and associated pod links"""

    def __init__(self, **kwargs):
        self.fields = []
        fields = list(objects.Pod.fields)
        # NOTE(lucasagomes): pod_uuid is not part of objects.Pod.fields
        #                    because it's an API-only attribute
        fields.append('pod_uuid')
        for field in fields:
            # Skip fields we do not expose.
            if not hasattr(self, field):
                continue
            self.fields.append(field)
            setattr(self, field, kwargs.get(field, wtypes.Unset))

        # NOTE(lucasagomes): pod_id is an attribute created on-the-fly
        # by _set_pod_uuid(), it needs to be present in the fields so
        # that as_dict() will contain pod_id field when converting it
        # before saving it in the database.
        self.fields.append('pod_id')
        setattr(self, 'pod_uuid', kwargs.get('pod_id', wtypes.Unset))

    @staticmethod
    def _convert_with_links(pod, url, expand=True):
        if not expand:
            pod.unset_fields_except(['uuid', 'name', 'desc', 'bay_uuid'])

        # never expose the pod_id attribute
        pod.pod_id = wtypes.Unset

        pod.links = [link.Link.make_link('self', url,
                                          'pods', pod.uuid),
                      link.Link.make_link('bookmark', url,
                                          'pods', pod.uuid,
                                          bookmark=True)
                     ]
        return pod

    @classmethod
    def convert_with_links(cls, rpc_pod, expand=True):
        pod = Pod(**rpc_pod.as_dict())
        return cls._convert_with_links(pod, pecan.request.host_url, expand)

    @classmethod
    def sample(cls, expand=True):
        sample = cls(uuid='f978db47-9a37-4e9f-8572-804a10abc0aa',
                     name='MyPod',
                     desc='Pod - Description',
                     bay_uuid='7ae81bb3-dec3-4289-8d6c-da80bd8001ae',
                     created_at=datetime.datetime.utcnow(),
                     updated_at=datetime.datetime.utcnow())
        # NOTE(lucasagomes): pod_uuid getter() method look at the
        # _pod_uuid variable
        sample._pod_uuid = '87504bd9-ca50-40fd-b14e-bcb23ed42b27'
        return cls._convert_with_links(sample, 'http://localhost:9511', expand)


class PodCollection(collection.Collection):
    """API representation of a collection of pods."""

    pods = [Pod]
    """A list containing pods objects"""

    def __init__(self, **kwargs):
        self._type = 'pods'

    @staticmethod
    def convert_with_links(rpc_pods, limit, url=None, expand=False, **kwargs):
        collection = PodCollection()
        collection.pods = [Pod.convert_with_links(p, expand)
                            for p in rpc_pods]
        collection.next = collection.get_next(limit, url=url, **kwargs)
        return collection

    @classmethod
    def sample(cls):
        sample = cls()
        sample.pods = [Pod.sample(expand=False)]
        return sample


class PodsController(rest.RestController):
    """REST controller for Pods."""

    from_pods = False
    """A flag to indicate if the requests to this controller are coming
    from the top-level resource Pods."""

    _custom_actions = {
        'detail': ['GET'],
    }

    def _get_pods_collection(self, marker, limit,
                              sort_key, sort_dir, expand=False,
                              resource_url=None):

        limit = api_utils.validate_limit(limit)
        sort_dir = api_utils.validate_sort_dir(sort_dir)

        marker_obj = None
        if marker:
            marker_obj = objects.Pod.get_by_uuid(pecan.request.context,
                                                  marker)

        pods = objects.Pod.list(pecan.request.context, limit,
                                marker_obj, sort_key=sort_key,
                                sort_dir=sort_dir)

        return PodCollection.convert_with_links(pods, limit,
                                                url=resource_url,
                                                expand=expand,
                                                sort_key=sort_key,
                                                sort_dir=sort_dir)

    @wsme_pecan.wsexpose(PodCollection, types.uuid,
                         types.uuid, int, wtypes.text, wtypes.text)
    def get_all(self, pod_uuid=None, marker=None, limit=None,
                sort_key='id', sort_dir='asc'):
        """Retrieve a list of pods.

        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        """
        return self._get_pods_collection(marker, limit, sort_key,
                                         sort_dir)

    @wsme_pecan.wsexpose(PodCollection, types.uuid,
                         types.uuid, int, wtypes.text, wtypes.text)
    def detail(self, pod_uuid=None, marker=None, limit=None,
                sort_key='id', sort_dir='asc'):
        """Retrieve a list of pods with detail.

        :param pod_uuid: UUID of a pod, to get only pods for that pod.
        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        """
        # NOTE(lucasagomes): /detail should only work agaist collections
        parent = pecan.request.path.split('/')[:-1][-1]
        if parent != "pods":
            raise exception.HTTPNotFound

        expand = True
        resource_url = '/'.join(['pods', 'detail'])
        return self._get_pods_collection(marker, limit,
                                         sort_key, sort_dir, expand,
                                         resource_url)

    @wsme_pecan.wsexpose(Pod, types.uuid)
    def get_one(self, pod_uuid):
        """Retrieve information about the given pod.

        :param pod_uuid: UUID of a pod.
        """
        if self.from_pods:
            raise exception.OperationNotPermitted

        rpc_pod = objects.Pod.get_by_uuid(pecan.request.context, pod_uuid)
        return Pod.convert_with_links(rpc_pod)

    @wsme_pecan.wsexpose(Pod, body=Pod, status_code=201)
    def post(self, pod):
        """Create a new pod.

        :param pod: a pod within the request body.
        """
        if self.from_pods:
            raise exception.OperationNotPermitted

        new_pod = objects.Pod(pecan.request.context,
                                **pod.as_dict())
        new_pod.create()
        # Set the HTTP Location Header
        pecan.response.location = link.build_url('pods', new_pod.uuid)
        return Pod.convert_with_links(new_pod)

    @wsme.validate(types.uuid, [PodPatchType])
    @wsme_pecan.wsexpose(Pod, types.uuid, body=[PodPatchType])
    def patch(self, pod_uuid, patch):
        """Update an existing pod.

        :param pod_uuid: UUID of a pod.
        :param patch: a json PATCH document to apply to this pod.
        """
        if self.from_pods:
            raise exception.OperationNotPermitted

        rpc_pod = objects.Pod.get_by_uuid(pecan.request.context, pod_uuid)
        try:
            pod_dict = rpc_pod.as_dict()
            # NOTE(lucasagomes):
            # 1) Remove pod_id because it's an internal value and
            #    not present in the API object
            # 2) Add pod_uuid
            pod_dict['pod_uuid'] = pod_dict.pop('pod_id', None)
            pod = Pod(**api_utils.apply_jsonpatch(pod_dict, patch))
        except api_utils.JSONPATCH_EXCEPTIONS as e:
            raise exception.PatchError(patch=patch, reason=e)

        # Update only the fields that have changed
        for field in objects.Pod.fields:
            try:
                patch_val = getattr(pod, field)
            except AttributeError:
                # Ignore fields that aren't exposed in the API
                continue
            if patch_val == wtypes.Unset:
                patch_val = None
            if rpc_pod[field] != patch_val:
                rpc_pod[field] = patch_val

        if hasattr(pecan.request, 'rpcapi'):
            rpc_pod = objects.Pod.get_by_id(pecan.request.context,
                                             rpc_pod.pod_id)
            topic = pecan.request.rpcapi.get_topic_for(rpc_pod)

            new_pod = pecan.request.rpcapi.update_pod(
                pecan.request.context, rpc_pod, topic)

            return Pod.convert_with_links(new_pod)
        else:
            rpc_pod.save()
            return Pod.convert_with_links(rpc_pod)

    @wsme_pecan.wsexpose(None, types.uuid, status_code=204)
    def delete(self, pod_uuid):
        """Delete a pod.

        :param pod_uuid: UUID of a pod.
        """
        if self.from_pods:
            raise exception.OperationNotPermitted

        rpc_pod = objects.Pod.get_by_uuid(pecan.request.context,
                                            pod_uuid)
        rpc_pod.destroy()
