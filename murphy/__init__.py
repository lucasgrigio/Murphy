"""Murphy — AI-driven website evaluation powered by browser-use."""

__version__ = '1.0.0'

from murphy.analysis import analyze_website as analyze_website
from murphy.execution import execute_tests as execute_tests
from murphy.execution import execute_tests_with_session as execute_tests_with_session
from murphy.generation import explore_and_generate_plan as explore_and_generate_plan
from murphy.generation import generate_tests as generate_tests
from murphy.judge import murphy_judge as murphy_judge
from murphy.models import JudgeVerdict as JudgeVerdict
from murphy.summary import build_summary as build_summary
from murphy.summary import classify_failure as classify_failure
