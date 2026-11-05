"""A fake Starlink dish gRPC server with reflection, built from a tiny stand-in schema.

The schema mimics the shape of the dish's `SpaceX.API.Device.Device/Handle` service
(field numbers as documented in docs/integrations/starlink.md) with only a few fields.
It is not SpaceX's definition.
"""

from __future__ import annotations

from typing import Any

import grpc
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from grpc_reflection.v1alpha import reflection

T = descriptor_pb2.FieldDescriptorProto


def _file() -> descriptor_pb2.FileDescriptorProto:
    f = descriptor_pb2.FileDescriptorProto(
        name="fake_dish.proto", package="SpaceX.API.Device", syntax="proto3"
    )

    def message(name: str, fields: list[tuple[str, int, int, str | None, int | None]]) -> None:
        m = f.message_type.add(name=name)
        for fname, number, ftype, type_name, oneof in fields:
            fd = m.field.add(name=fname, number=number, type=ftype, label=T.LABEL_OPTIONAL)
            if type_name:
                fd.type_name = type_name
            if oneof is not None:
                fd.oneof_index = oneof
        if any(o is not None for *_, o in fields):
            m.oneof_decl.add(name="request" if name == "Request" else "response")

    for empty in (
        "GetStatusRequest",
        "GetHistoryRequest",
        "GetDeviceInfoRequest",
        "DishStowRequest",
    ):
        message(empty, [])
    message(
        "DeviceInfo",
        [("id", 1, T.TYPE_STRING, None, None), ("software_version", 3, T.TYPE_STRING, None, None)],
    )
    message(
        "DishGetStatusResponse",
        [
            ("device_info", 1, T.TYPE_MESSAGE, ".SpaceX.API.Device.DeviceInfo", None),
            ("pop_ping_latency_ms", 1009, T.TYPE_FLOAT, None, None),
        ],
    )
    message(
        "Request",
        [
            ("get_status", 1004, T.TYPE_MESSAGE, ".SpaceX.API.Device.GetStatusRequest", 0),
            ("get_history", 1007, T.TYPE_MESSAGE, ".SpaceX.API.Device.GetHistoryRequest", 0),
            ("get_device_info", 1008, T.TYPE_MESSAGE, ".SpaceX.API.Device.GetDeviceInfoRequest", 0),
            ("dish_stow", 2002, T.TYPE_MESSAGE, ".SpaceX.API.Device.DishStowRequest", 0),
        ],
    )
    message(
        "Response",
        [("dish_get_status", 2004, T.TYPE_MESSAGE, ".SpaceX.API.Device.DishGetStatusResponse", 0)],
    )
    svc = f.service.add(name="Device")
    svc.method.add(
        name="Handle",
        input_type=".SpaceX.API.Device.Request",
        output_type=".SpaceX.API.Device.Response",
    )
    return f


async def start_fake_dish() -> tuple[grpc.aio.Server, int, list[str]]:
    pool = descriptor_pool.DescriptorPool()
    pool.Add(_file())
    request_cls: Any = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("SpaceX.API.Device.Request")
    )
    response_cls: Any = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("SpaceX.API.Device.Response")
    )
    received: list[str] = []

    async def handle(request: Any, context: Any) -> Any:
        received.append(request.WhichOneof("request") or "")
        response = response_cls()
        if request.WhichOneof("request") == "get_status":
            response.dish_get_status.device_info.id = "ut0000-fake"
            response.dish_get_status.device_info.software_version = "2026.10.09"
            response.dish_get_status.pop_ping_latency_ms = 41.5
        return response

    server = grpc.aio.server()
    handler = grpc.method_handlers_generic_handler(
        "SpaceX.API.Device.Device",
        {
            "Handle": grpc.unary_unary_rpc_method_handler(
                handle,
                request_deserializer=request_cls.FromString,
                response_serializer=lambda m: m.SerializeToString(),
            )
        },
    )
    server.add_generic_rpc_handlers((handler,))
    reflection.enable_server_reflection(
        ["SpaceX.API.Device.Device", reflection.SERVICE_NAME], server, pool=pool
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    return server, port, received
