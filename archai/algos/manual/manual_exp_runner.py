
from typing import Optional, Type

from overrides import overrides

from archai.common.config import Config
from archai.nas import nas_utils
from archai.nas.exp_runner import ExperimentRunner
from archai.nas.arch_trainer import ArchTrainer, TArchTrainer
from archai.nas.cell_builder import CellBuilder

class ManualExperimentRunner(ExperimentRunner):
    """Runs manually designed models such as resnet"""

    @overrides
    def run_search(self)->Config:
        raise NotImplementedError('Cannot perform search on manually crafted nn.Module, only eval is allowed')

    @overrides
    def cell_builder(self)->Optional[CellBuilder]:
        return None

    @overrides
    def trainer_class(self)->TArchTrainer:
        return None # no search trainer


