################################################################################
# Copyright (c) 2021 ContinualAI.                                              #
# Copyrights licensed under the MIT License.                                   #
# See the accompanying LICENSE file for terms.                                 #
#                                                                              #
# Date: 01-12-2020                                                             #
# Author(s): Andrea Cossu                                                      #
# E-mail: contact@continualai.org                                              #
# Website: avalanche.continualai.org                                           #
################################################################################
"""
This example trains on Split CIFAR10 with Naive strategy.
In this example each experience has a different task label.
We use a multi-head model with a separate classifier for each task.
"""

import argparse
import random
from collections import defaultdict
from typing import Sequence

import dill
import numpy as np
import torch
from torch.nn import CrossEntropyLoss
from torch.optim import SGD

from avalanche.benchmarks import CLExperience, SplitCIFAR100
from avalanche.benchmarks.classic import SplitCIFAR10
from avalanche.evaluation.metrics import accuracy_metrics, loss_metrics, \
    class_accuracy_metrics
from avalanche.logging import InteractiveLogger, TextLogger, TensorboardLogger
from avalanche.models import SimpleMLP, as_multitask
from avalanche.training.determinism.rng_manager import RNGManager
from avalanche.training.plugins import EvaluationPlugin, CWRStarPlugin, \
    ReplayPlugin
from avalanche.training.plugins.checkpoint import CheckpointPlugin, \
    FileSystemCheckpointStorage
from avalanche.training.supervised import Naive


def main(args):
    RNGManager.set_random_seeds(1234)
    torch.use_deterministic_algorithms(True)

    # Config
    device = torch.device(
        f"cuda:{args.cuda}"
        if torch.cuda.is_available() and args.cuda >= 0
        else "cpu"
    )
    print('Using device', device)

    # CL Benchmark Creation
    scenario = SplitCIFAR100(n_experiences=5, return_task_id=True)
    train_stream: Sequence[CLExperience] = scenario.train_stream
    test_stream: Sequence[CLExperience] = scenario.test_stream

    # Define the model (and load initial weights if necessary)
    model = SimpleMLP(input_size=32 * 32 * 3, num_classes=scenario.n_classes//5)
    model = as_multitask(model, 'classifier')

    # Prepare for training & testing
    optimizer = SGD(model.parameters(), lr=0.01, momentum=0.9)
    criterion = CrossEntropyLoss()

    # Define the checkpoint plugin
    checkpoint_plugin = CheckpointPlugin(
        FileSystemCheckpointStorage(
            directory='./checkpoints/task_incremental',
        ),
        map_location=device
    )

    # Load checkpoint (if exists)
    strategy, initial_exp = checkpoint_plugin.load_checkpoint_if_exists()

    # Create the CL strategy (if not already loaded from checkpoint)
    if strategy is None:
        plugins = [
            checkpoint_plugin
        ]

        # Create other plugins
        # ...
        cli_plugins = []
        cli_plugin_names = '_'.join(args.plugins)
        for cli_plugin in args.plugins:

            if cli_plugin == 'cwr':
                plugin_instance = CWRStarPlugin(
                    model, freeze_remaining_model=False)
            elif cli_plugin == 'replay':
                plugin_instance = ReplayPlugin(mem_size=500)
            else:
                raise ValueError('Unrecognized plugin name from CLI.')
            print('Adding plugin', plugin_instance)
            cli_plugins.append(plugin_instance)
        plugins += cli_plugins

        # Create the evaluation plugin (when not using the default one)
        evaluation_plugin = EvaluationPlugin(
            accuracy_metrics(minibatch=False, epoch=True,
                             experience=True, stream=True),
            loss_metrics(minibatch=False, epoch=True,
                         experience=True, stream=True),
            class_accuracy_metrics(
                stream=True
            ),
            loggers=[
                # TextLogger(open('text_logger_test_out.txt', 'w')),
                InteractiveLogger(),
                TensorboardLogger(f'./logs/checkpointing{args.checkpoint_at}_'
                                  f'{cli_plugin_names}')
            ]
        )

        # Create the strategy
        strategy = Naive(
            model=model,
            optimizer=optimizer,
            criterion=criterion,
            train_mb_size=128,
            train_epochs=2,
            eval_mb_size=128,
            device=device,
            plugins=plugins,
            evaluator=evaluation_plugin
        )

    # Train and test loop
    for train_task in train_stream[initial_exp:]:
        strategy.train(train_task, num_workers=0)
        strategy.eval(test_stream)
        if train_task.current_experience == args.checkpoint_at:
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cuda",
        type=int,
        default=0,
        help="Select zero-indexed cuda device. -1 to use CPU.",
    )
    parser.add_argument(
        "--checkpoint_at",
        type=int,
        default=-1
    )
    parser.add_argument(
        "--plugins",
        nargs='*',
        required=False,
        default=[]
    )
    args = parser.parse_args()
    main(args)
