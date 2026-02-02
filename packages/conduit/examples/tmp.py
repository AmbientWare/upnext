from conduit import Api, Worker, get_current_context

api = Api("test-api", host="0.0.0.0", port=8080)
worker = Worker("test-worker", concurrency=100, redis_url="redis://localhost:6379")

hello_event = worker.event("hello")


@hello_event.on
async def hello_handler(message: str):
    # print the context
    ctx = get_current_context()
    print(ctx)
    print(f"Received: {message}")
    return {"received": message}


@worker.task()
async def hello_task(message: str):
    print(f"Received: {message}")
    return {"received": message}


@api.get("/hello")
async def hello():
    # hello_handler.send() is typed - IDE knows it needs message: str
    await hello_handler.send(message="Hello, World!")
    await hello_task.submit(message="Hello, World!")
    return {"message": "Hello, World!"}
