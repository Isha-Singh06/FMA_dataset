import numpy as np
import ctypes
import multiprocessing
import multiprocessing.sharedctypes as sharedctypes
import os.path

FMA_METADATA = ['artist', 'title', 'genres', 'play_count']
TOP_GENRE = 'top_genre'
SPLIT = 'train'

ECHONEST_METADATA = ['release', 'artist_location', 'artist_name', 'album_date',
                     'album_name']

ECHONEST_AUDIO_FEATURES = ['acousticness', 'danceability', 'energy',
                           'instrumentalness', 'liveness', 'speechiness',
                           'tempo', 'valence']
ECHONEST_TEMPORAL_FEATURES = 'temporal_echonest_features'

ECHONEST_SOCIAL_FEATURES = ['artist_discovery', 'artist_familiarity',
                            'artist_hotttnesss', 'song_hotttnesss',
                            'song_currency']
ECHONEST_RANKS = ['artist_discovery_rank', 'artist_familiarity_rank',
                  'artist_hotttnesss_rank', 'song_currency_rank',
                  'song_hotttnesss_rank']

# Number of samples per 30s audio clip.
# TODO: fix dataset to be constant.
NB_AUDIO_SAMPLES = 1321967


def build_path(df, data_dir):
    def path(index):
        genre = df.iloc[index]['top_genre']
        tid = df.iloc[index].name
        return os.path.join(data_dir, genre, str(tid) + '.mp3')
    return path


def build_sample_loader(path, Y):

    class SampleLoader:

        def __init__(self, ids, batch_size=4):
            self.lock1 = multiprocessing.Lock()
            self.lock2 = multiprocessing.Lock()
            self.batch_foremost = sharedctypes.RawValue(ctypes.c_int, 0)
            self.batch_rearmost = sharedctypes.RawValue(ctypes.c_int, -1)
            self.condition = multiprocessing.Condition(lock=self.lock2)

            data = sharedctypes.RawArray(ctypes.c_int, ids.data)
            self.ids = np.ctypeslib.as_array(data)

            self.batch_size = batch_size

            self.X = np.empty((self.batch_size, NB_AUDIO_SAMPLES))
            self.Y = np.empty((self.batch_size, Y.shape[1]))

        def __iter__(self):
            return self

        def __next__(self):

            with self.lock1:
                if self.batch_foremost.value == 0:
                    np.random.shuffle(self.ids)

                batch_current = self.batch_foremost.value
                if self.batch_foremost.value + self.batch_size < self.ids.size:
                    batch_size = self.batch_size
                    self.batch_foremost.value += self.batch_size
                else:
                    batch_size = self.ids.size - self.batch_foremost.value
                    self.batch_foremost.value = 0

                # print(self.ids, self.batch_foremost.value, batch_current, self.ids[batch_current], batch_size)
                # print('queue', self.ids[batch_current], batch_size)
                indices = np.array(self.ids[batch_current:batch_current+batch_size])

            for i, idx in enumerate(indices):
                x = self._load_ffmpeg(path(idx))
                self.X[i] = x[:NB_AUDIO_SAMPLES]
                self.Y[i] = Y[idx]

            with self.lock2:
                while (batch_current - self.batch_rearmost.value) % self.ids.size > self.batch_size:
                    # print('wait', indices[0], batch_current, self.batch_rearmost.value)
                    self.condition.wait()
                self.condition.notify_all()
                # print('yield', indices[0], batch_current, self.batch_rearmost.value)
                self.batch_rearmost.value = batch_current

                return self.X[:batch_size], self.Y[:batch_size]

        def _load_librosa(self, filename):
            import librosa
            x, sr = librosa.load(filename, sr=None)
            return x

        def _load_audioread(self, filename):
            import audioread
            a = audioread.audio_open(filename)
            a.read_data()

        def _load_pydub(self, filename):
            from pydub import AudioSegment
            song = AudioSegment.from_file(filename)
            song = song.set_channels(1)
            x = song.get_array_of_samples()
            # print(filename) if song.channels != 2 else None
            return np.array(x)

        def _load_ffmpeg(self, filename):
            """Fastest and less CPU intensive loading method."""
            import subprocess as sp
            command = ['ffmpeg',
                       '-i', filename,
                       '-f', 's16le',
                       '-acodec', 'pcm_s16le',
                       # '-ar', '44100', # sampling rate
                       '-ac', '1',  # channels: 2 for stereo, 1 for mono
                       '-']
            # 30s at 44.1 kHz ~= 1.3e6
            proc = sp.run(command, stdout=sp.PIPE, bufsize=10**7)
            return np.fromstring(proc.stdout, dtype="int16")

    return SampleLoader