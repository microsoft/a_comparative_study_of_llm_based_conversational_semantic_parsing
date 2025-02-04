# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import asyncio
import dataclasses
import itertools
import operator
import random
from dataclasses import dataclass
from typing import (
    AbstractSet,
    Awaitable,
    Callable,
    FrozenSet,
    Generic,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    TypeVar,
    Union,
)

from semantic_parsing_with_constrained_lm.tokenization import ClampTokenizer

TrainDatum = TypeVar("TrainDatum")
TestDatum = TypeVar("TestDatum")
T = TypeVar("T")


@dataclass(frozen=True, eq=True)
class Adornment:
    """Text that you put around some data.

    For few-shot modeling, a typical prefix might be 'Input: ' and suffix '\n'.
    """

    prefix: str
    suffix: str


@dataclass(frozen=True, eq=True)
class ProblemSpec:
    """Defines a set of input fields, and one output field."""

    input_fields: FrozenSet[str]
    output_field: str


@dataclass
class PromptBuilder(Generic[TrainDatum, TestDatum]):
    """Builds prompts for few-shot tasks with language models.

    Each datum has one or more input fields, and one output field. To build
    the prompt, we use the input fieldss and the output field for a set of
    training data, and the input fields for the test datum.

    For example, let's say that we're doing machine translation from French to English.
    Then we might set this up like the following:
    PromptBuilder(
        problem_spec=ProblemSpec(input_fields=frozenset(["french"]), output_field="english"),
        preamble="Let's translate from French to English!\n\n"  # A description of the task
        input_field_order=["french"],
        field_to_adornment={
            "french": Adornment("French: ", "\n"),
            "english": Adornment("English: ", "\n"),
        },
        separator="---\n",
    )

    Then when given two training datums, it would generate text like the following:
    > Let's translate from French to English!
    >
    > ---
    > French: train 1 french
    > English: train 1 english
    > ---
    > French: train 2 french
    > English: train 2 english
    > ---
    > French: test french
    > English:

    If a datum has `None` as the value for a given input field, that field is skipped.

    See tests for more examples.
    """

    problem_spec: ProblemSpec

    # Placed at the beginning of each prompt.
    preamble: Optional[str]
    input_field_order: Sequence[str]
    field_to_adornment: Mapping[str, Adornment]
    datum_adornment: Adornment = Adornment(prefix="", suffix="")
    separator: str = ""

    def __post_init__(self):
        assert self.problem_spec.input_fields == set(self.input_field_order)
        assert self.problem_spec.input_fields | {self.problem_spec.output_field} == set(
            self.field_to_adornment.keys()
        )

    def assemble(
        self, train_data: Sequence[TrainDatum], test_datum: Optional[TestDatum]
    ) -> str:
        def build_one_datum(
            datum: Union[TrainDatum, TestDatum], fields: Iterable[str]
        ) -> str:
            result_here: List[str] = []
            result_here += [self.datum_adornment.prefix]
            for field in fields:
                value = getattr(datum, field, None)
                if value is None:
                    continue
                adornment = self.field_to_adornment[field]
                result_here += [
                    adornment.prefix,
                    value,
                    adornment.suffix,
                ]
            result_here += [self.datum_adornment.suffix]
            return "".join(result_here)

        result: List[str] = []
        if self.preamble:
            result += [self.preamble]
        for datum in train_data:
            result += [
                build_one_datum(
                    datum,
                    itertools.chain(
                        self.input_field_order, [self.problem_spec.output_field]
                    ),
                )
            ]
        if test_datum is not None:
            result += [
                build_one_datum(test_datum, self.input_field_order)
                + self.field_to_adornment[self.problem_spec.output_field].prefix
            ]
        
        return self.separator.join(result)

    @property
    def stop(self) -> str:
        """The string which marks the end of the output for the test datum."""
        return self.field_to_adornment[self.problem_spec.output_field].suffix

    @property
    def fixed_text_before_output(self) -> str:
        """The complete text which always appears before where the output should go."""
        return (
            self.field_to_adornment[self.input_field_order[-1]].suffix
            + self.field_to_adornment[self.problem_spec.output_field].prefix
        )

    @staticmethod
    def for_demo(
        do_include_context: bool, use_preamble: bool = True
    ) -> "PromptBuilder":
        input_field_order = (["agent_context"] if do_include_context else []) + [
            "natural"
        ]
        field_to_adornment = {
            "natural": Adornment("Human: ", "\n"),
            "canonical": Adornment("Computer: ", "\n"),
        }
        if do_include_context:
            field_to_adornment["agent_context"] = Adornment("Agent: ", "\n")
        return PromptBuilder(
            problem_spec=ProblemSpec(
                input_fields=frozenset(input_field_order), output_field="canonical"
            ),
            preamble="Let's translate what a human user says into what a computer might say.\n\n"
            if use_preamble
            else None,
            input_field_order=input_field_order,
            field_to_adornment=field_to_adornment,
            separator="\n",
        )


class DataRetriever(Generic[TrainDatum, TestDatum]):
    """
    A selector that selects prompts from a pre-built index.
    """

    async def __call__(self, test_datum: TestDatum) -> Sequence[TrainDatum]:
        raise NotImplementedError


class DataFilter(Generic[TrainDatum, TestDatum]):
    async def __call__(
        self, train_data: Sequence[TrainDatum], test_datum: TestDatum
    ) -> Sequence[TrainDatum]:
        """
        train_data:
        - outer Sequence: "train data pieces", or in other words,
                          groups of TrainDatum (e.g. to ensemble over multiple prompts)
        - inner Sequence: TrainDatums to use in a specific prompt

        test_datum: the datum that we will run against on the training data
        """
        raise NotImplementedError


@dataclass
class TopKSimilar(DataRetriever[TrainDatum, TestDatum]):
    """Retrieves the top K similar examples according to a scoring function."""

    train_data: Sequence[TrainDatum]
    scorer: Callable[[TrainDatum, TestDatum], Awaitable[float]]
    k: int
    best_first: bool = True

    async def __call__(self, test_datum: TestDatum) -> Sequence[TrainDatum]:
        if self.k == 0:
            return []

        # First we get the top-scoring K TrainDatums
        scores = await asyncio.gather(
            *[self.scorer(train_datum, test_datum) for train_datum in self.train_data]  # type: ignore
        )
        sorted_data = list(zip(self.train_data, scores))
        sorted_data.sort(reverse=self.best_first, key=operator.itemgetter(1))
        relevant_data = (
            sorted_data[: self.k] if self.best_first else sorted_data[-self.k :]
        )
        result = tuple(example for example, _ in relevant_data)

        return result


@dataclass
class ShuffleAndSample(DataFilter[TrainDatum, TestDatum]):
    # Number of train datums to put in each piece.
    num_per_sample: int
    random_seed: int

    async def __call__(
        self, train_data: Sequence[TrainDatum], _test_datum: TestDatum
    ) -> Sequence[TrainDatum]:
        if self.num_per_sample == 0:
            return []

        shuffle_rand = random.Random(self.random_seed)
        data = list(train_data)
        shuffle_rand.shuffle(data)
        return data[: self.num_per_sample]


MAX_TOKEN_LENGTH = 2048


@dataclass
class TruncateTokenLength(DataFilter[TrainDatum, TestDatum]):
    """
    Truncates each train data group so that the prompt is no more than MAX_TOKEN_LENGTH - completion_length
    long.
    """

    prompt_builder: PromptBuilder

    # Upper bound on length of the GPT3 completion.
    completion_length: int

    tokenizer: ClampTokenizer

    # If True, truncate the first items in the group.
    reverse: bool = False
    max_test_length: int = dataclasses.field(init=False)

    def __post_init__(self):
        self.max_test_length = MAX_TOKEN_LENGTH - self.completion_length

    async def __call__(
        self, train_data: Sequence[TrainDatum], test_datum: TestDatum
    ) -> Sequence[TrainDatum]:
        return (
            self._build_group_reverse(train_data, test_datum)
            if self.reverse
            else self._build_group_forward(train_data, test_datum)
        )

    def _build_group_forward(
        self, train: Sequence[TrainDatum], test_datum: TestDatum
    ) -> Sequence[TrainDatum]:
        num_pruned_examples = 0
        group: List[TrainDatum] = []
        for t in train:
            if (
                len(
                    self.tokenizer.tokenize(
                        self.prompt_builder.assemble(group + [t], test_datum)
                    )
                )
                < self.max_test_length
            ):
                group.append(t)
            else:
                num_pruned_examples += 1

        if num_pruned_examples > 0:
            print(f"Prompt creation had to be cut off {num_pruned_examples} examples")
        return group

    def _build_group_reverse(
        self, train: Sequence[TrainDatum], test_datum: TestDatum
    ) -> Sequence[TrainDatum]:
        num_pruned_examples = 0
        group: List[TrainDatum] = []
        for t in reversed(train):
            if (
                len(
                    self.tokenizer.tokenize(
                        self.prompt_builder.assemble([t] + group, test_datum)
                    )
                )
                < self.max_test_length
            ):
                group = [t] + group
            else:
                num_pruned_examples += 1

        if num_pruned_examples > 0:
            print(f"Prompt creation had to be cut off {num_pruned_examples} examples")
        return group


class InvalidForGPT2Tokenizer(Exception):
    pass


@dataclass
class GPT2TokenizerQuirks:
    """Methods for handling unintuitive consequences of GPT-2 tokenization."""

    tokenizer: ClampTokenizer
    space_tokens: Optional[Set[int]] = None
    prompt_ends_in_space: Optional[bool] = None

    def check_prompt_builder(self, prompt_builder: PromptBuilder) -> None:
        output_prefix = prompt_builder.fixed_text_before_output
        if len(output_prefix) == 0:
            raise InvalidForGPT2Tokenizer("A non-empty output prefix is required")
        if output_prefix[-1] == "\n":
            self.prompt_ends_in_space = False
        elif output_prefix[-1] == " ":
            self.prompt_ends_in_space = True
        else:
            raise InvalidForGPT2Tokenizer(
                "Output prefix does not end in a newline or a space. Please "
                "think hard about how that interacts with the tokenizer and add a "
                "new elif here if you still want to use that prompt style."
            )

    def check_initial_allowed_tokens(
        self, tokens: Optional[AbstractSet[int]], can_end: bool
    ) -> None:
        if self.prompt_ends_in_space is None:
            raise Exception("Run check_prompt_builder() first")

        if not self.prompt_ends_in_space:
            return

        if self.space_tokens is None:
            self.space_tokens = {
                i
                for token, i in self.tokenizer.utf8_token_to_id_map.items()
                if token.startswith(b" ")
            }

        if can_end:
            raise InvalidForGPT2Tokenizer(
                "Can't end with no tokens; need to generate at least a space"
            )
        if tokens is None or len(tokens - self.space_tokens) != 0:
            raise InvalidForGPT2Tokenizer("All allowed tokens must start with a space")

    def postprocess_prompt(self, prompt: str) -> str:
        """Adapt the prompt to not end in a space"""
        if self.prompt_ends_in_space is None:
            raise Exception("Run check_prompt_builder() first")
        if self.prompt_ends_in_space:
            return prompt[:-1]
        else:
            return prompt

    def postprocess_result(self, result: str) -> str:
        if self.prompt_ends_in_space is None:
            raise Exception("Run check_prompt_builder() first")
        if self.prompt_ends_in_space:
            return result[1:]
        else:
            return result
