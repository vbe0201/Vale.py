import asyncio
import subprocess


async def run_subprocess(cmd, loop=None):
    loop = loop or asyncio.get_event_loop()
    try:
        process = await asyncio.create_subprocess_shell(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except NotImplementedError:
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True) as process:
            try:
                result = await loop.run_in_executor(None, process.communicate)
            except Exception:  # muh pycodestyle
                def kill():
                    process.kill()
                    process.wait()

                await loop.run_in_executor(None, kill)
                raise

    else:
        result = await process.communicate()

    return [res.decode('utf-8') for res in result]
