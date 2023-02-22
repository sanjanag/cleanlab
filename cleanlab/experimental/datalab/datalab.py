# Copyright (C) 2017-2023  Cleanlab Inc.
# This file is part of cleanlab.
#
# cleanlab is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# cleanlab is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with cleanlab.  If not, see <https://www.gnu.org/licenses/>.
"""
Implements cleanlab's Datalab interface as a one-stop-shop for tracking
and managing all kinds of issues in datasets.

.. note::
    .. include:: optional_dependencies.rst
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast
import warnings

import numpy as np
import numpy.typing as npt
import pandas as pd

import cleanlab
from cleanlab.experimental.datalab.data import Data
from cleanlab.experimental.datalab.data_issues import DataIssues
from cleanlab.experimental.datalab.display import _Displayer
from cleanlab.experimental.datalab.factory import _IssueManagerFactory
from cleanlab.experimental.datalab.serialize import _Serializer

if TYPE_CHECKING:  # pragma: no cover
    from datasets.arrow_dataset import Dataset

    DatasetLike = Union[Dataset, pd.DataFrame, Dict[str, Any], List[Dict[str, Any]], str]

__all__ = ["Datalab"]


class Datalab:
    """
    A single object to automatically detect all kinds of issues in datasets.
    This is how we recommend you interface with the cleanlab library if you want to audit the quality of your data. If you have other specific goals, then consider using the other methods across this library. Even then, Datalab may be the easiest way to run specific analyses of your data. Datalab tracks intermediate state (e.g. data statistics) from certain cleanlab functions that can be re-used across other cleanlab functions for better efficiency.

    Parameters
    ----------
    data : Union[Dataset, pd.DataFrame, dict, list, str]
        Dataset-like object that can be converted to a Hugging Face Dataset object.

        It should contain the labels for all examples, identified by a
        `label_name` column in the Dataset object.

        See also
        --------
        :py:class:`Data <cleanlab.experimental.datalab.data.Data>`:
        Internal class that represents the dataset.


    label_name :
        The name of the label column in the dataset.

    verbosity : int, optional
        The verbosity level of the Datalab object. The higher the verbosity,
        the more information is printed to the console.
        Valid values are 0 through 4. Default is 1.

    Examples
    --------
    >>> import datasets
    >>> from cleanlab import Datalab
    >>> data = datasets.load_dataset("glue", "sst2", split="train")
    >>> datalab = Datalab(data, label_name="label")
    """

    def __init__(
        self,
        data: "DatasetLike",
        label_name: Union[str, List[str]],
        verbosity: int = 1,
    ) -> None:
        self._data = Data(data, label_name)  # TODO: Set extracted class instance to self.data
        self.data = self._data._data
        self._labels, self._label_map = self._data._labels, self._data._label_map
        self._data_hash = self._data._data_hash
        self.label_name = self._data._label_name
        self.data_issues = DataIssues(self._data)
        self.cleanlab_version = cleanlab.version.__version__
        self.path = ""
        self.verbosity = verbosity

    def __repr__(self) -> str:
        """What is displayed if user executes: datalab"""
        return _Displayer(self).__repr__()

    def __str__(self) -> str:
        """What is displayed if user executes: print(datalab)"""
        return _Displayer(self).__str__()

    @property
    def labels(self) -> np.ndarray:
        """Labels of the dataset, in a [0, 1, ..., K-1] format."""
        return self._labels

    @property
    def issues(self) -> pd.DataFrame:
        """Issues found in the dataset."""
        return self.data_issues.issues

    @issues.setter
    def issues(self, issues: pd.DataFrame) -> None:
        self.data_issues.issues = issues

    @property
    def issue_summary(self) -> pd.DataFrame:
        """Summary of issues found in the dataset.

        Example
        -------

        If checks for "label" and "outlier" issues were run,
        then the issue summary will look something like this:

        >>> datalab.issue_summary
        issue_type  score
        outlier     0.123
        label       0.456
        """
        return self.data_issues.issue_summary

    @issue_summary.setter
    def issue_summary(self, issue_summary: pd.DataFrame) -> None:
        self.data_issues.issue_summary = issue_summary

    @property
    def info(self) -> Dict[str, Dict[str, Any]]:
        """Information and statistics about the dataset issues found.

        Example
        -------

        If checks for "label" and "outlier" issues were run,
        then the info will look something like this:

        >>> datalab.info
        {
            "label": {
                "given_labels": [0, 1, 0, 1, 1, 1, 1, 1, 0, 1, ...],
                "predicted_label": [0, 0, 0, 1, 0, 1, 0, 1, 0, 1, ...],
                ...,
            },
            "outlier": {
                "nearest_neighbor": [3, 7, 1, 2, 8, 4, 5, 9, 6, 0, ...],
                "distance_to_nearest_neighbor": [0.123, 0.789, 0.456, ...],
                ...,
            },
        }
        """
        return self.data_issues.info

    @info.setter
    def info(self, info: Dict[str, Dict[str, Any]]) -> None:
        self.data_issues.info = info

    def _resolve_required_args(self, pred_probs, features, model):
        """Resolves the required arguments for each issue type.

        This is a helper function that filters out any issue manager
        that does not have the required arguments.

        This does not consider custom hyperparameters for each issue type.


        Parameters
        ----------
        pred_probs :
            Out-of-sample predicted probabilities made on the data.

        features :
            Name of column containing precomputed embeddings.

        model :
            sklearn compatible model used to compute out-of-sample predicted probabilities for the labels.

        Returns
        -------
        args_dict :
            Dictionary of required arguments for each issue type, if available.
        """
        args_dict = {
            "label": {"pred_probs": pred_probs, "model": model},
            "outlier": {"pred_probs": pred_probs, "features": features},
            "near_duplicate": {"features": features},
            "non_iid": {"features": features},
        }

        args_dict = {
            k: {k2: v2 for k2, v2 in v.items() if v2 is not None} for k, v in args_dict.items() if v
        }

        # TODO: Check for any missing arguments that are required for each issue type.
        args_dict = {k: v for k, v in args_dict.items() if v}

        return args_dict

    def _set_issue_types(
        self,
        issue_types: Optional[Dict[str, Any]],
        required_defaults_dict: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Set necessary configuration for each IssueManager in a dictionary.

        While each IssueManager defines default values for its arguments,
        the Datalab class needs to organize the calls to each IssueManager
        with different arguments, some of which may be

        Parameters
        ----------
        issue_types :
            Dictionary of issue types and argument configuration for their respective IssueManagers.
            If None, then the `required_defaults_dict` is used.

        required_defaults_dict :
            Dictionary of default parameter configuration for each issue type.

        Returns
        -------
        issue_types_copy :
            Dictionary of issue types and their parameter configuration.
            The input `issue_types` is copied and updated with the necessary default values.
        """
        if issue_types is not None:
            issue_types_copy = issue_types.copy()
            self._check_missing_args(required_defaults_dict, issue_types_copy)
        else:
            issue_types_copy = required_defaults_dict.copy()
        # Check that all required arguments are provided.
        self._validate_issue_types_dict(issue_types_copy, required_defaults_dict)

        # Remove None values from argument list, rely on default values in IssueManager
        for key, value in issue_types_copy.items():
            issue_types_copy[key] = {k: v for k, v in value.items() if v is not None}
        return issue_types_copy

    @staticmethod
    def _check_missing_args(required_defaults_dict, issue_types):
        for key, issue_type_value in issue_types.items():
            missing_args = set(required_defaults_dict.get(key, {})) - set(issue_type_value.keys())
            # Impute missing arguments with default values.
            missing_dict = {
                missing_arg: required_defaults_dict[key][missing_arg]
                for missing_arg in missing_args
            }
            issue_types[key].update(missing_dict)

    @staticmethod
    def _validate_issue_types_dict(
        issue_types: Dict[str, Any], required_defaults_dict: Dict[str, Any]
    ) -> None:
        missing_required_args_dict = {}
        for issue_name, required_args in required_defaults_dict.items():
            if issue_name in issue_types:
                missing_args = set(required_args.keys()) - set(issue_types[issue_name].keys())
                if missing_args:
                    missing_required_args_dict[issue_name] = missing_args
        if any(missing_required_args_dict.values()):
            error_message = ""
            for issue_name, missing_required_args in missing_required_args_dict.items():
                error_message += f"Required argument {missing_required_args} for issue type {issue_name} was not provided.\n"
            raise ValueError(error_message)

    def _get_report(self, num_examples: int, verbosity: int, include_description: bool) -> str:
        # Sort issues based on the score
        # Show top k issues
        # Show the info (get_info) with some verbosity level
        #   E.g. for label issues, only show the confident joint computed with the health_summary
        report_str = ""
        issue_type_sorted = self._sort_issue_summary_by_issue_counts(self.issue_summary)
        report_str += self._add_issue_summary_to_report(summary=issue_type_sorted)
        issue_type_sorted_keys: List[str] = issue_type_sorted["issue_type"].tolist()
        issue_manager_reports = []
        for key in issue_type_sorted_keys:
            issue_manager_class = _IssueManagerFactory.from_str(issue_type=key)
            issue_manager_reports.append(
                issue_manager_class.report(
                    issues=self.get_issues(issue_name=key),
                    summary=self.get_summary(issue_name=key),
                    info=self.get_info(issue_name=key),
                    num_examples=num_examples,
                    verbosity=verbosity,
                    include_description=include_description,
                )
            )

        report_str += "\n\n\n".join(issue_manager_reports)
        return report_str

    def _sort_issue_summary_by_issue_counts(self, issue_summary: pd.DataFrame) -> pd.DataFrame:
        """Sort issue_summary by the number of issues per issue type.

        Returns
        -------
        sorted_summary :
            Sorted issue_summary.

        Examples
        --------
        >>> issue_summary = pd.DataFrame(
        ...     {
        ...         "issue_type": ["label", "outlier", "near_duplicate"],
        ...         "score": [0.5, 0.2, 0.1],
        ...     }
        ... )
        >>> # Calling this method will sort the issue_summary by the number of issues
        >>> sorted_summary = Datalab._sort_issue_summary_by_issue_counts(issue_summary)
        >>> sorted_summary
               issue_type  score  num_issues
        0         outlier    0.2           5
        1           label    0.5           3
        2  near_duplicate    0.1           2
        """
        summary = issue_summary.copy()
        names = summary["issue_type"].tolist()
        counts = [self.get_issues(issue_name=name)[f"is_{name}_issue"].sum() for name in names]
        # Rank issue_summary by the number of issues in issue_type_counts
        summary["num_issues"] = counts
        # issue_type_sorted = self.issue_summary.sort_values(by="score", ascending=True)
        sorted_summary = summary.sort_values(by="num_issues", ascending=False)
        return sorted_summary

    def get_issues(self, issue_name: Optional[str] = None) -> pd.DataFrame:
        """
        Fetch information about each individual issue found in the data for a specific issue type.

        Parameters
        ----------
        issue_name : str or None
            The name of the issue type to retrieve. If `None`, returns the entire `issues` DataFrame.

        Raises
        ------
        ValueError
            If `issue_name` is not found in the `issues` DataFrame.

        Returns
        -------
        specific_issues :
            A DataFrame containing the issues data for the specified issue type, or the entire `issues`
            DataFrame if `issue_name` is `None`.

            Additional columns are added to the DataFrame if `issue_name` is "label".
        """
        if issue_name is None:
            return self.issues

        specific_issues = self._get_matching_issue_columns(issue_name)
        if issue_name == "label":
            label_info = self.get_info(issue_name=issue_name)
            predicted_labels = np.vectorize(self._data._label_map.get)(
                label_info["predicted_label"]
            )
            label_name = cast(str, self.label_name)
            specific_issues = specific_issues.assign(
                given_label=self._data._data[label_name], predicted_label=predicted_labels
            )
        return specific_issues

    def _get_matching_issue_columns(self, issue_name: str) -> pd.DataFrame:
        columns = [col for col in self.issues.columns if issue_name in col]
        if not columns:
            raise ValueError(f"No columns found for issue type '{issue_name}'.")
        return self.issues[columns]

    def get_summary(self, issue_name: Optional[str] = None) -> pd.DataFrame:
        """Get summary of issues for a given issue type.

        Parameters
        ----------
        issue_name :
            Name of the issue type.

        Returns
        -------
        summary :
            Summary of issues for a given issue type.
        """
        if self.issue_summary.empty:
            raise ValueError(
                "No issues found in the dataset. "
                "Call `find_issues` before calling `get_summary`."
            )

        if issue_name is None:
            return self.issue_summary

        row_mask = self.issue_summary["issue_type"] == issue_name
        if not any(row_mask):
            raise ValueError(f"Issue type {issue_name} not found in the summary.")
        return self.issue_summary[row_mask].reset_index(drop=True)

    def _add_issue_summary_to_report(self, summary: pd.DataFrame) -> str:
        return (
            "Here is a summary of the different kinds of issues found in the data:\n\n"
            + summary.to_string(index=False)
            + "\n\n"
            + "(Note: A lower score indicates a more severe issue across all examples in the dataset.)\n\n\n"
        )

    def find_issues(
        self,
        *,
        pred_probs: Optional[np.ndarray] = None,
        issue_types: Optional[Dict[str, Any]] = None,
        features: Optional[npt.NDArray] = None,
        model=None,  # sklearn.Estimator compatible object  # noqa: F821
    ) -> None:
        """
        Checks for all sorts of issues in the data, including in labels and in features.

        Can utilize either provided model or pred_probs.

        Note
        ----
        The issues are saved in self.issues, but are not returned.

        Parameters
        ----------
        pred_probs :
            Out-of-sample predicted probabilities made on the data.

        issue_types :
            Collection of the types of issues to search for.

            Keyword arguments to pass to the IssueManager constructor.

            .. seealso::
                IssueManager

            It is a dictionary of dictionaries, where the keys are the issue types
            and the values are dictionaries of keyword arguments to pass to the
            IssueManager constructor.

            WARNING
            -------
            If an empty dictionary is passed, no issues will be found.

            Example
            -------
            For example, if you want to pass the keyword argument "clean_learning_kwargs"
            to the constructor of the LabelIssueManager, you would pass:


            .. code-block:: python

                issue_init_kwargs = {
                    "label": {
                        "clean_learning_kwargs": {
                            "prune_method": "prune_by_noise_rate",
                        },
                    },
                }

        features :
            Precomputed feature embeddings of the data.

        model :
            sklearn compatible model used to compute out-of-sample
            predicted probability for the labels.

            WARNING
            -------
            This is not yet implemented.
        """

        if issue_types is not None and not issue_types:
            warnings.warn(
                "No issue types were specified. " "No issues will be found in the dataset."
            )
            return None

        required_args_per_issue_type = self._resolve_required_args(pred_probs, features, model)

        issue_types_copy = self._set_issue_types(issue_types, required_args_per_issue_type)

        new_issue_managers = [
            factory(datalab=self, **issue_types_copy.get(factory.issue_name, {}))
            for factory in _IssueManagerFactory.from_list(list(issue_types_copy.keys()))
        ]

        failed_managers = []
        for issue_manager, arg_dict in zip(new_issue_managers, issue_types_copy.values()):
            try:
                if self.verbosity:
                    print(f"Finding {issue_manager.issue_name} issues ...")
                issue_manager.find_issues(**arg_dict)
                self.data_issues._collect_results_from_issue_manager(issue_manager)
            except Exception as e:
                print(f"Error in {issue_manager.issue_name}: {e}")
                failed_managers.append(issue_manager)

        if self.verbosity:
            print("Search complete.")
        if failed_managers:
            print(f"Failed to find issues for {failed_managers}")

    def get_info(self, issue_name: Optional[str] = None) -> Dict[str, Any]:
        """Returns dict of info about a specific issue,
        or None if this issue does not exist in self.info.
        Internally fetched from self.info[issue_name] and prettified.
        Keys might include: number of examples suffering from issue,
        indicates of top-K examples most severely suffering,
        other misc stuff like which sets of examples are duplicates if the issue=="duplicated".
        """  # TODO: Revise Datalab.get_info docstring
        return self.data_issues.get_info(issue_name)

    def report(
        self,
        num_examples: int = 5,
        verbosity: Optional[int] = None,
        include_description: bool = True,
    ) -> None:
        """Prints helpful summary of all issues.

        Parameters
        ----------
        num_examples :
            Number of examples to show for each type of issue.

        verbosity :
            Level of verbosity. 0 is the default and prints the top num_examples examples
            for each issue. Higher levels may add more information to the report.
        """
        if verbosity is None:
            verbosity = self.verbosity
        # Show summary of issues
        print(
            self._get_report(
                num_examples=num_examples,
                verbosity=verbosity,
                include_description=include_description,
            )
        )

    def save(self, path: str) -> None:
        """Saves this Lab to file (all files are in folder at path/).
        Uses nice format for the DF attributes (csv) and dict attributes (eg. json if possible).
        We do not guarantee saved Lab can be loaded from future versions of cleanlab.

        You have to save the Dataset yourself if you want it saved to file!
        """  # TODO: Revise Datalab.save docstring: Formats and guarantees
        _Serializer.serialize(path=path, datalab=self)
        save_message = f"Saved Datalab to folder: {path}"
        print(save_message)

    @staticmethod
    def load(path: str, data: Optional[Dataset] = None) -> "Datalab":
        """Loads Lab from file. Folder could ideally be zipped or unzipped.

        Checks which cleanlab version Lab was previously saved from
        and raises warning if they dont match.

        If a Dataset is passed (via the `data` argument), it will be added to the Datalab
        if it matches the Dataset that was used to create the Datalab.

        Parameters
        ----------

        `path` :
            Path to the folder containing the save Datalab and
            associated files, not the Dataset.
        """  # TODO: Revise Datalab.load docstring: Zipped/unzipped, guarantees
        datalab = _Serializer.deserialize(path=path, data=data)
        load_message = f"Datalab loaded from folder: {path}"
        print(load_message)
        return datalab
