"""
Code to run the World Cup tournament, from group stages through the
knockout stages, to the final, and produce a winner.
"""

import random
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from .bpl_interface import WCPred
from .data_loader import get_fixture_data, get_teams_data
from .utils import (
    find_group,
    predict_group_match,
    predict_knockout_match,
    sort_teams_by,
)


class Group:
    def __init__(self, name: str, teams: List[str]):
        self.name = name
        self.teams = np.array(teams)

        # "table" is a dictionary keyed by team name, with the points, gf,ga
        self.table = None

        # "standings" is a dictionary with keys "1st", "2nd", "3rd", "4th"
        # and values being the team names.
        self.standings = None

        # results is a dict of played matches
        # dict {
        # "home_team": <team_name>,
        # "away_team": <team_name>,
        # "home_score": <score>,"
        # away_score": <score>"
        # }
        self.results = None

        # order of criteria for deciding group order
        self.metrics = [
            "points",
            "goal_difference",
            "goals_for",
            "head-to-head",
            "random",
        ]

    def calc_table(self) -> None:
        """
        Go through the results, and add points and goals to the table
        """
        home_pts = 3 * (self.results["home_score"] > self.results["away_score"])
        away_pts = 3 * (self.results["home_score"] < self.results["away_score"])
        draw = self.results["home_score"] == self.results["away_score"]
        home_pts[draw] = 1
        away_pts[draw] = 1

        self.table = {
            "points": np.full(
                (len(self.teams), self.results["home_score"].shape[1]), np.nan
            ),
            "goals_for": np.full(
                (len(self.teams), self.results["home_score"].shape[1]), np.nan
            ),
            "goals_against": np.full(
                (len(self.teams), self.results["home_score"].shape[1]), np.nan
            ),
            "goal_difference": np.full(
                (len(self.teams), self.results["home_score"].shape[1]), np.nan
            ),
        }

        for team_idx, team in enumerate(self.teams):
            team_home_idx = self.results["home_team"] == team
            team_home_pts = home_pts[team_home_idx].sum(axis=0)
            team_home_goals_for = self.results["home_score"][team_home_idx].sum(axis=0)
            team_home_goals_against = self.results["away_score"][team_home_idx].sum(
                axis=0
            )

            team_away_idx = self.results["away_team"] == team
            team_away_pts = away_pts[team_away_idx].sum(axis=0)
            team_away_goals_for = self.results["away_score"][team_away_idx].sum(axis=0)
            team_away_goals_against = self.results["home_score"][team_away_idx].sum(
                axis=0
            )

            self.table["points"][team_idx, :] = team_home_pts + team_away_pts
            self.table["goals_for"][team_idx, :] = (
                team_home_goals_for + team_away_goals_for
            )
            self.table["goals_against"][team_idx, :] = (
                team_home_goals_against + team_away_goals_against
            )
            self.table["goal_difference"][team_idx, :] = (
                self.table["goals_for"][team_idx, :]
                - self.table["goals_against"][team_idx, :]
            )

    def get_qualifiers(self) -> Tuple:
        """
        return the two teams that topped the group
        """
        if self.standings is None:
            self.calc_standings()
        first = np.nonzero(self.standings.T == 1)[1]
        second = np.nonzero(self.standings.T == 2)[1]
        return self.teams[first], self.teams[second]

    def fill_standings_position(
        self, team: str, position: int, verbose: bool = False
    ) -> None:
        """
        Fill specified slot in our team standings.
        """
        if self.standings[position]:
            raise RuntimeError("Position {} is already filled!".format(position))
        if verbose:
            print("Putting {} in {}".format(team, position))
        self.standings[position] = team
        return

    def find_head_to_head_winner(self, team_A: str, team_B: str) -> Tuple[str, str]:
        team_1 = None
        team_2 = None
        for result in self.results:
            if set(result.keys()) == set([team_A, team_B]):
                if result[team_A] > result[team_B]:
                    team_1 = team_A
                    team_2 = team_B
                elif result[team_B] > result[team_A]:
                    team_1 = team_B
                    team_2 = team_A
                break
        return team_1, team_2

    def set_positions_using_metric(
        self,
        teams_to_sort: List[str],
        positions_to_fill: List[str],
        metric: str,
        verbose: bool = False,
    ) -> None:
        if len(teams_to_sort) != len(positions_to_fill):
            raise RuntimeError(
                f"Can't fill {len(positions_to_fill)} positions with "
                f"{len(teams_to_sort)} teams"
            )
        if verbose:
            print(
                "Sorting {} using {} to fill positions {}".format(
                    teams_to_sort, metric, positions_to_fill
                )
            )
        # if random, just shuffle our list
        if metric == "random":
            random.shuffle(teams_to_sort)
            for i, pos in enumerate(positions_to_fill):
                self.fill_standings_position(teams_to_sort[i], pos)
            if verbose:
                print("randomly assigned {} teams".format(len(teams_to_sort)))
            return
        elif metric == "head-to-head":
            if len(teams_to_sort) > 2:
                print("Can't use head-to-head for more than 2 teams")
                # skip ahead to random
                self.set_positions_using_metric(
                    teams_to_sort, positions_to_fill, "random"
                )
            else:
                team_1, team_2 = self.find_head_to_head_winner(
                    teams_to_sort[0], teams_to_sort[1]
                )
                if team_1 and team_2:  # not null if there was a winner
                    self.fill_standings_position(team_1, positions_to_fill[0])
                    self.fill_standings_position(team_2, positions_to_fill[1])
                else:
                    # go to random
                    self.set_positions_using_metric(
                        teams_to_sort, positions_to_fill, "random"
                    )
            return
        # ok, otherwise we need to sort the table by the metric
        team_dict = {t: self.table[t] for t in teams_to_sort}
        team_scores = sort_teams_by(team_dict, metric)  # list of dicts of teams
        team_list = [t["team"] for t in team_scores]  # ordered list of teams
        # figure out the next metric, in case this one doesn't differentiate
        current_metric_index = self.metrics.index(metric)
        new_metric = self.metrics[current_metric_index + 1]

        # OK, let's get sorting!! Start with two-team case
        if len(team_list) == 2:
            if team_scores[0][metric] > team_scores[1][metric]:  # one team is better
                self.fill_standings_position(team_list[0], positions_to_fill[0])
                self.fill_standings_position(team_list[1], positions_to_fill[1])
                return
            else:
                # they are equal - call this func again with the next metric
                self.set_positions_using_metric(
                    team_list, positions_to_fill, new_metric
                )
                return
        elif len(team_list) == 3:
            # 4 possible cases
            if (
                team_scores[0][metric] > team_scores[1][metric]
                and team_scores[1][metric] > team_scores[2][metric]
            ):  # 1st > 2nd > 3rd
                self.fill_standings_position(team_list[0], positions_to_fill[0])
                self.fill_standings_position(team_list[1], positions_to_fill[1])
                self.fill_standings_position(team_list[2], positions_to_fill[2])
                return  # we are done!
            elif (
                team_scores[0][metric] > team_scores[1][metric]
                and team_scores[1][metric] == team_scores[2][metric]
            ):  # last two equal
                self.fill_standings_position(team_list[0], positions_to_fill[0])
                # call this func again with the last two, and the next metric
                self.set_positions_using_metric(
                    team_list[1:], positions_to_fill[1:], new_metric
                )
                return
            elif (
                team_scores[0][metric] == team_scores[1][metric]
                and team_scores[1][metric] > team_scores[2][metric]
            ):  # first two equal
                self.fill_standings_position(team_list[2], positions_to_fill[2])
                # call this func again with the first two, and the next metric
                self.set_positions_using_metric(
                    team_list[:2], positions_to_fill[:2], new_metric
                )
            else:  # all three teams equal - just move onto the next metric
                self.set_positions_using_metric(
                    team_list, positions_to_fill, new_metric
                )
            return
        elif len(team_list) == 4:  # 8 possible cases.
            if verbose:
                print("TEAM LIST", team_scores)
            if (
                team_scores[0][metric] > team_scores[1][metric]
                and team_scores[1][metric] > team_scores[2][metric]
                and team_scores[2][metric] > team_scores[3][metric]
            ):  # case 1) all in order
                self.fill_standings_position(team_list[0], "1st")
                self.fill_standings_position(team_list[1], "2nd")
                self.fill_standings_position(team_list[2], "3rd")
                self.fill_standings_position(team_list[3], "4th")
                # we are done!
                return
            elif (
                team_scores[0][metric] == team_scores[1][metric]
                and team_scores[1][metric] > team_scores[2][metric]
                and team_scores[2][metric] > team_scores[3][metric]
            ):  # case 2) first two equal
                self.fill_standings_position(team_list[2], "3rd")
                self.fill_standings_position(team_list[3], "4th")
                # call this func with the first two and the next metric
                self.set_positions_using_metric(
                    team_list[:2], positions_to_fill[:2], new_metric
                )
            elif (
                team_scores[0][metric] > team_scores[1][metric]
                and team_scores[1][metric] == team_scores[2][metric]
                and team_scores[2][metric] > team_scores[3][metric]
            ):  # case 3) middle two equal
                self.fill_standings_position(team_list[0], "1st")
                self.fill_standings_position(team_list[3], "4th")
                # call this func with the middle two and the next metric
                self.set_positions_using_metric(
                    team_list[1:3], positions_to_fill[1:3], new_metric
                )
            elif (
                team_scores[0][metric] > team_scores[1][metric]
                and team_scores[1][metric] > team_scores[2][metric]
                and team_scores[2][metric] == team_scores[3][metric]
            ):  # case 4) last two equal
                self.fill_standings_position(team_list[0], "1st")
                self.fill_standings_position(team_list[1], "2nd")
                # call this func with the last two and the next metric
                self.set_positions_using_metric(
                    team_list[2:], positions_to_fill[2:], new_metric
                )
            elif (
                team_scores[0][metric] == team_scores[1][metric]
                and team_scores[1][metric] == team_scores[2][metric]
                and team_scores[2][metric] > team_scores[3][metric]
            ):  # case 5) all equal except last
                self.fill_standings_position(team_list[3], "4th")
                # call this func with the first three and the next metric
                self.set_positions_using_metric(
                    team_list[:3], positions_to_fill[:3], new_metric
                )
            elif (
                team_scores[0][metric] > team_scores[1][metric]
                and team_scores[1][metric] == team_scores[2][metric]
                and team_scores[2][metric] == team_scores[3][metric]
            ):  # case 6) all equal except first
                self.fill_standings_position(team_list[0], "1st")
                # call this func with the last three and the next metric
                self.set_positions_using_metric(
                    team_list[1:], positions_to_fill[1:], new_metric
                )
            elif (
                team_scores[0][metric] == team_scores[1][metric]
                and team_scores[1][metric] > team_scores[2][metric]
                and team_scores[2][metric] == team_scores[3][metric]
            ):  # case 7) nightmare scenario!!
                # call func with first two and next metric
                self.set_positions_using_metric(
                    team_list[:2], positions_to_fill[:2], new_metric
                )
                # call func with last two and next metric
                self.set_positions_using_metric(
                    team_list[2:], positions_to_fill[2:], new_metric
                )
            else:  # case 8) all equal - carry on to next metric
                # call this func with the last three and the next metric
                self.set_positions_using_metric(
                    team_list, positions_to_fill, new_metric
                )
            return

    def calc_standings(self, head_to_head=False) -> None:
        """
        sort the table, and try and assign positions in the standings

        if not head_to_head sort by points -> goal difference -> goals -> random
        (i.e. don't consider head to head as a tiebreaker)
        """
        if self.table is None:
            self.calc_table()

        if not head_to_head:
            self.standings = len(self.teams) - np.lexsort(
                (
                    np.random.random(size=self.table["points"].shape),
                    self.table["goals_for"],
                    self.table["goal_difference"],
                    self.table["points"],
                ),
                axis=0,
            )
        else:
            raise NotImplementedError("Not updated head-to-head logic")
            # reset the standings table to start from scratch
            for k in self.standings.keys():
                self.standings[k] = None
            # now calculate the standings again
            self.set_positions_using_metric(
                self.teams, ["1st", "2nd", "3rd", "4th"], "points"
            )

    def check_if_result_exists(self, team_1, team_2):
        """
        See if we already have a result for these two teams.
        Parameters
        ==========
        team_1, team_2: both str, team names, as in teams.csv
        Returns
        =======
        True if result already stored, False otherwise
        """
        for result in self.results:
            if set([team_1, team_2]) == set(result.keys()):
                return True
        return False

    def add_results(self, results):
        """
        Add a result for a group-stage match.
        Parameters
        ==========
        fixtures: dict of results (with keys 'home_team', 'away_team', 'home_score',
        'away_score')
        results: Simulated match scores for all fixtures in df
        """
        group_mask = np.isin(results["home_team"], self.teams)
        self.results = {
            "home_team": results["home_team"][group_mask],
            "away_team": results["away_team"][group_mask],
            "home_score": np.array(results["home_score"])[group_mask],
            "away_score": np.array(results["away_score"])[group_mask],
        }

    def __str__(self) -> str:
        max_team_name_length = 0
        for t in self.teams:
            if len(t) > max_team_name_length:
                max_team_name_length = len(t)

        output = f"Position |  Team{' '*(max_team_name_length-8)}| Points | GS |  GA \n"
        self.calc_standings()
        for k, v in self.standings.items():
            output += (
                f"   {k}    {v}{' '*(max_team_name_length-len(v))}   "
                f"{self.table[v]['points']}      {self.table[v]['goals_for']}     "
                f"{self.table[v]['goals_against']} \n"
            )
        return output


class Tournament:
    def __init__(self, year: str = "2022", num_samples=1):
        self.teams_df = get_teams_data(year)
        self.fixtures_df = get_fixture_data(year)
        self.group_names = list(set(self.teams_df["Group"].values))
        self.groups = {}
        for n in self.group_names:
            g = Group(n, list(self.teams_df[self.teams_df["Group"] == n].Team.values))
            self.groups[n] = g
        self.aliases = pd.DataFrame(index=np.arange(num_samples))
        self.is_complete = False
        self.num_samples = num_samples

    def add_result(
        self, team_1: str, team_2: str, score_1: int, score_2: int, stage: str
    ) -> None:
        """
        Enter a match result explicitly

        Parameters
        ==========
        team_1, team_2: both str, names of teams, as in teams.csv
        score_1, score_2: both int, scores of respective teams
        stage: str, must be "Group", "R16", "QF", "SF", "F"
        """
        # find the fixture
        for idx, row in self.fixtures_df.iterrows():
            if stage != row.Stage:
                continue
            if stage == "Group":
                if set([row.Team_1, row.Team_2]) == set([team_1, team_2]):
                    # find the group
                    group = find_group(team_1, self.teams_df)
                    self.groups[group].add_result(team_1, team_2, score_1, score_2)

    def play_group_stage(
        self,
        wc_pred: WCPred,
        seed: Optional[int] = None,
        head_to_head: bool = False,
    ) -> None:
        group_fixtures = self.fixtures_df[self.fixtures_df.Stage == "Group"]
        results = wc_pred.simulate_score(
            group_fixtures["Team_1"],
            group_fixtures["Team_2"],
            seed=seed,
            num_samples=self.num_samples,
        )
        for g in self.groups.values():
            g.add_results(results)
            g.calc_standings(head_to_head=head_to_head)

    def play_knockout_stages(
        self, wc_pred: WCPred, seed: Optional[int] = None, verbose: bool = False
    ) -> None:
        """
        For the round of 16, assign the first and second place teams
        from each group to the aliases e.g. "A1", "B2"
        """
        for g in self.groups.values():
            t1, t2 = g.get_qualifiers()
            self.aliases["1" + g.name] = t1
            self.aliases["2" + g.name] = t2

        for stage in ["R16", "QF", "SF", "F"]:
            print(stage)
            stage_fixtures = self.fixtures_df[self.fixtures_df["Stage"] == stage]

            results = wc_pred.simulate_outcome(
                self.aliases[stage_fixtures["Team_1"]].values.flatten(),
                self.aliases[stage_fixtures["Team_2"]].values.flatten(),
                seed=seed,
                num_samples=1,
            ).reshape((self.num_samples, len(stage_fixtures)))

            self.aliases[stage_fixtures["Team_1"] + stage_fixtures["Team_2"]] = results

            if stage == "F":
                self.winner = results.flatten()

        self.is_complete = True

    def get_furthest_position_for_team(self, team_name):
        """
        Given a team name, see how far they got in the tournament.

        Parameters
        ==========
        team_name: str, one of the team names, as defined in teams.csv

        Returns
        =======
        "G", "R16", "QF", "SF", "RU", "W" depending on how far the team got.
        """
        if not self.is_complete:
            print("Tournament is not yet complete")
            return None
        if self.winner == team_name:
            return "W"
        elif team_name not in self.aliases.values():
            return "G"
        else:
            # the length of the 'alias' string, e.g. "1A2B" shows how far a team got
            key_length_lookup = {2: "R16", 4: "QF", 8: "SF", 16: "RU"}
            # convert the aliases dict into a list, and sort by length of the key
            # (this will represent how far the team got - if we look in reverse order
            # of key length, we will find the latest stage a team got to first)
            alias_list = [(k, v) for k, v in self.aliases.items()]
            sorted_aliases = sorted(alias_list, key=lambda x: len(x[0]), reverse=True)
            for k, v in sorted_aliases:
                if v == team_name:
                    return key_length_lookup[len(k)]
            # we should never get to here
            raise RuntimeError(f"Unable to find team {team_name} in aliases table")
