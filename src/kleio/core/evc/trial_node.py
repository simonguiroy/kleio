from kleio.core.evc.tree import TreeNode
from kleio.core.io.cmdline_parser import CmdlineParser
from kleio.core.io.database import Database
from kleio.core.trial.attribute import (
    event_based_property, event_based_diff, EventBasedItemAttribute)
from kleio.core.trial.base import Trial
from kleio.core.utils import flatten, unflatten

from kleio.core.trial.statistics import Statistics


class TrialNode(TreeNode):

    @classmethod
    def build(cls, interval=(None, None), **kwargs):
        trial = Trial.build(interval=interval, **kwargs)
        return TrialNode(trial.id, trial)

    @classmethod
    def load(cls, trial_id, interval=(None, None)):
        trial = Trial.load(trial_id, interval=interval)
        return TrialNode(trial_id, trial)

    @classmethod
    def view(cls, trial_id, interval=(None, None)):
        trial = Trial.view(trial_id, interval=interval)
        return TrialNode(trial_id, trial)

    @classmethod
    def branch(cls, trial_id, timestamp=None, **kwargs):
        """Builder method for a list of trials.

        :param trial_entries: List of trial representation in dictionary form,
           as expected to be saved in a database.

        :returns: a list of corresponding `Trial` objects.
        """
        parent_node = cls.view(trial_id, interval=(None, timestamp))
        timestamp = timestamp if timestamp else parent_node.end_time

        kwargs['refers'] = {
            'parent_id': trial_id,
            'timestamp': timestamp
        }
        cmdline_parser = CmdlineParser()
        cmdline_parser.parse(parent_node.commandline.split(" "))
        configuration = parent_node.configuration
        configuration.update(kwargs['configuration'])
        commandline = cmdline_parser.format(configuration)
        branch_configuration = cmdline_parser.parse(kwargs['commandline'])
        configuration.update(branch_configuration)
        commandline = cmdline_parser.format(configuration)
        kwargs['commandline'] = commandline.split(" ")
        branch = Trial(**kwargs)

        return TrialNode(branch.id, branch, parent=parent_node)

    def __init__(self, trial_id, trial=None, parent=None, children=tuple()):
        self.id = trial_id
        self._no_parent_lookup = True
        self._no_children_lookup = True
        super(TrialNode, self).__init__(trial, parent, children)

    def __getattr__(self, name):
        item = TreeNode.__getattribute__(self, 'item')
        if hasattr(item, name):
            return getattr(item, name)

        raise AttributeError(name)

    @property
    def item(self):
        """Get the experiment associated to the node

        Note that accessing `item` may trigger the lazy initialization of the experiment if it was
        not done already.
        """
        if self._item is None:
            print("loading view")
            self._item = Trial.view(self.id)
            self._item._trial._node = self

        return self._item

    @property
    def parent(self):
        """Get parent of the experiment, None if no parent

        .. note::

            The instantiation of an EVC tree is lazy, which means accessing the parent of a node
            may trigger a call to database to build this parent live.

        """
        if self._parent is None and self._no_parent_lookup:
            self._no_parent_lookup = False
            if self.item.refers['parent_id'] is not None:
                trial_id = self.item.refers['parent_id']
                timestamp = self.item.refers['timestamp']
                print("loading parent view")
                self.set_parent(TrialNode.view(trial_id, interval=(None, timestamp)))

        return self._parent

    @property
    def children(self):
        """Get children of the experiment, empty list if no children

        .. note::

            The instantiation of an EVC tree is lazy, which means accessing the children of a node
            may trigger a call to database to build those children live.

        """
        if not self._children and self._no_children_lookup:
            self._no_children_lookup = False
            query = {'refers.parent_id': self.item.id}
            selection = {'_id': 1}
            print("loading child view")
            trials = Database().read(self.item.trial_immutable_collection,
                                     query, selection=selection)
            for child in trials:
                self.add_children(TrialNode(child['_id']))

        return self._children

    @event_based_property
    def stdout(self):
        stdout = self.item.stdout

        if self.parent:
            stdout = self.parent.stdout + stdout

        return stdout

    @stdout.incrementer
    def stdout(self, new_lines):
        self.item.stdout += new_lines

    @event_based_property
    def stderr(self):
        stderr = self.item.stderr

        if self.parent:
            stderr = self.parent.stderr + stderr

        return stderr

    @stderr.incrementer
    def stderr(self, new_lines):
        self.item.stderr += new_lines

    def get_artifacts(self, filename, query):
        artifacts = self.item.get_artifacts(filename, query)

        if self.parent:
            artifacts = self.parent.get_artifacts(filename, query) + artifacts

        return artifacts

    @property
    def commandlines(self):
        commandlines = [(self.item.start_time, self.item.commandline)]

        if self.parent:
            commandlines = self.parent.commandlines + commandlines

        return commandlines

    def _get_event_based_diff_configuration(self):
        if self.parent:
            parent_configuration = self.parent._get_event_based_diff_configuration()
            return event_based_diff(
                self.parent.end_time, self.item.start_time,
                parent_configuration, self.item.configuration)

        return self.item.configuration

    @property
    def configuration(self):
        configuration = flatten(self._get_event_based_diff_configuration())
        for key, value in list(configuration.items()):
            if isinstance(value, EventBasedItemAttribute):
                configuration[key] = [(event['timestamp'], event['item']) for event in value]

        return unflatten(configuration)

    @property
    def hosts(self):
        hosts = [(self.item.start_time, self.item.host)]

        if self.parent:
            hosts = self.parent.hosts + hosts

        return hosts

    @property
    def versions(self):
        versions = [(self.item.start_time, self.item.version)]

        if self.parent:
            versions = self.parent.versions + versions

        return versions

    @property
    def statistics(self):
        history = self._statistics.history

        if self.parent:
            history = list(self.parent.statistics.history.values()) + history
        return Statistics(history)

    def __str__(self):
        """Represent partially with a string."""
        if self.parent:
            return "Trial(id={0}, status={1}, parent={2})".format(
                self.item.id, self.item.status, self.item.refers['parent_id'])

        return str(self.item)

    __repr__ = __str__
