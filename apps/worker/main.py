"""Worker service main loop.
Polls pending tasks and project runs, executes steps, and listens for emergency stop signals.
"""

import asyncio
import signal
from packages.agent.runtime import emergency_controls
from packages.observability.logger import logger
from packages.shared.database import async_session_factory, close_db, init_db

running = True


def handle_exit(*args):
    global running
    logger.info("Received termination signal. Gracefully exiting worker...")
    running = False


async def run_worker_loop():
    logger.info("Starting Autonomous Agent Worker Loop...")
    await init_db()

    while running:
        if emergency_controls.is_stopped:
            logger.info("Worker paused due to active emergency stop.")
            await asyncio.sleep(5)
            continue

        # In production: poll Redis task queue or database for pending ProjectTasks
        await asyncio.sleep(2)

    await close_db()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)
    asyncio.run(run_worker_loop())
