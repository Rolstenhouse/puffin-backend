import asyncio
import aiohttp
import os
import sys

from PIL import Image
from openai import AzureOpenAI

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.processors.aggregators.llm_response import (
    LLMAssistantResponseAggregator,
    LLMUserResponseAggregator,
)
from pipecat.frames.frames import (
    AudioRawFrame,
    ImageRawFrame,
    SpriteFrame,
    Frame,
    LLMMessagesFrame,
    TTSStoppedFrame,
    StopTaskFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.elevenlabs import ElevenLabsTTSService
from pipecat.services.openai import OpenAILLMService
from pipecat.transports.services.daily import (
    DailyParams,
    DailyTranscriptionSettings,
    DailyTransport,
    DailyTransportMessageFrame,
)
from pipecat.vad.silero import SileroVADAnalyzer
import prompts

from runner import configure

from loguru import logger

from dotenv import load_dotenv

load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

sprites = []

script_dir = os.path.dirname(__file__)

for i in range(1, 26):
    # Build the full path to the image file
    full_path = os.path.join(script_dir, f"assets/robot0{i}.png")
    # Get the filename without the extension to use as the dictionary key
    # Open the image and convert it to bytes
    with Image.open(full_path) as img:
        sprites.append(
            ImageRawFrame(image=img.tobytes(), size=img.size, format=img.format)
        )

flipped = sprites[::-1]
sprites.extend(flipped)

# When the bot isn't talking, show a static image of the cat listening


async def main(room_url: str, token: str, prompt_id: str = None):
    prompt = prompts.get_prompt(prompt_id)
    async with aiohttp.ClientSession() as session:
        transport = DailyTransport(
            room_url,
            token,
            "Chatbot",
            DailyParams(
                audio_out_enabled=True,
                camera_out_enabled=True,
                camera_out_width=1024,
                camera_out_height=576,
                vad_enabled=True,
                vad_analyzer=SileroVADAnalyzer(),
                transcription_enabled=True,
                #
                # Spanish
                #
                transcription_settings=DailyTranscriptionSettings(
                    language="en",
                    tier="nova",
                    model="2-conversationalai",
                    includeRawResponse=True,
                    extra={"diarize": True, "interim_results": True},
                ),
            ),
        )

        tts = ElevenLabsTTSService(
            aiohttp_session=session,
            api_key=os.getenv("ELEVENLABS_API_KEY"),
            voice_id="bXZsX0uAVHV9y9ZkPARP",
        )

        llm = OpenAILLMService(
            api_key=os.getenv("OPENAI_API_KEY"), model="gpt-4o", max_tokens=100
        )

        messages = [
            {
                "role": "system",
                "content": (
                    prompt
                    if prompt
                    else """ROLE: 
                        You are a couple's therapist responsible for the long-term growth of the couple. You should use the Gottman series as a style to ask great questions. Keep all statements to one sentence or one question at a time. You should help the couple grow closer and go deeper. 

                        ACTIONS:
                        First, ask the couple how they're doing, and to provide their names. (wait for them to anwer before proceeding to the next question)

                        Then, say that you'll ask questions and encourage each partner to take a turn answering the questions. Speaker 0 and speaker 1 in the input will refer to each partner accordingly.

                        Then, ask them if there's anything they'd like to talk about before getting started. (wait for them to answer before proceeding). If there is something, help them navigate the conversation.

                        WARMUP: 
                        Warm up the couple by telling them that this conversation will focus on questions around sex and intimacy. Ask them if they're comfortable with that topic. (wait for them to answer before proceeding to the next question)

                        QUESTIONS:
                        1. Think about all the times you have had sex. What are some of your favorites? What about that time made it your favorite?
                            - (Wait for both partners to respond before proceeding to the next question.)
                        2. What turns you on?
                            - (Wait for both partners to respond before proceeding to the next question.)
                        3. How can you bring more passion to your relationship? 
                            - (Wait for both partners to respond before proceeding to the next question.)
                        4. [Speaker 0], what's your favorite way to let [Speaker 1] know you want to have sex?
                            - (Wait for both partners to respond before proceeding to the next question.)
                        5. Where and how do you like to be touched?
                            - (Wait for both partners to respond before proceeding to the next question.)
                        6. What's your favorite time to make love and why? What's your favorite position?
                            - (Wait for both partners to respond before proceeding to the next question.)
                        7. Is there something sexually you've always wanted to try, but have never asked? How often would you like to have sex?
                            - (Wait for both partners to respond before proceeding to the next question.)
                        8. [Speaker 0], what can you do to make [Speaker 1]'s sex life better?
                            - (Wait for both partners to respond before proceeding to the next question.)

                        ANALYZING RESPONSES:
                        When one speaker responds to the other speaker, make sure that they acknowledge the response and occasionally briefly summarize what the other speaker has said.

                        You'll receive text input with [Speaker 0]: <text> indicates that the text was sent by Speaker 0. Text sent with [Speaker 1]: <text> indicates that the text was sent by Speaker 1. Do not refer to the speakers using the term speaker, but rather use the names they introduced themselves with. 

                        Replace [Speaker 0] or [Speaker 1] in your output with the names provided by the individuals. 

                        Speaker 0 will refer to only one speaker. Speaker 1 will refer to the other. Track which speaker corresponds to which name. 
                        """
                ),
            },
        ]

        user_response = LLMUserResponseAggregator(messages)
        assistant_response = LLMAssistantResponseAggregator(messages)

        pipeline = Pipeline(
            [
                transport.input(),
                user_response,
                llm,
                tts,
                transport.output(),
                assistant_response,
            ]
        )
        LLM_INTRO_PROMPT = {
            "role": "system",
            "content": "You are a couple's therapist. Your goal is to get the couple to introduce themselves. Ask them how they're doing and to provide their names. (wait for them to answer before proceeding to the next question)",
        }

        task = PipelineTask(pipeline, PipelineParams(allow_interruptions=True))

        CUE_USER_TURN = {"cue": "user_turn"}
        CUE_ASSISTANT_TURN = {"cue": "assistant_turn"}

        @transport.event_handler("on_first_participant_joined")
        async def on_first_participant_joined(transport, participant):
            transport.capture_participant_transcription(participant["id"])
            await task.queue_frames([LLMMessagesFrame([LLM_INTRO_PROMPT])])

        runner = PipelineRunner()

        await runner.run(task)


if __name__ == "__main__":
    (url, token, prompt_id) = configure()
    asyncio.run(main(url, token, prompt_id))
